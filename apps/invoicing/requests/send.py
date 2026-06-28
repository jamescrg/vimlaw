"""Send a payment request: email the catch-up pay link + the matter ledger
statement to the client. Mirrors apps.invoicing.invoices.functions.send_invoice.
"""

import os

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from apps.invoicing.pay.links import request_pay_url
from apps.matters.ledger.generate_ledger import generate_ledger
from apps.settings.models import Company
from utils.mail import render_inlined


class PaymentRequestSendError(Exception):
    pass


def send_payment_request(payment_request, *, message=None, request=None):
    """Email the request's pay link + the matter ledger statement PDF to the
    recipient. Returns True; raises PaymentRequestSendError on failure."""
    matter = payment_request.matter
    client = matter.client if matter else None
    to = (payment_request.recipient_email or "").strip()
    if not to:
        raise PaymentRequestSendError("No recipient email address on file.")

    company = Company.objects.first()
    bcc_list = (
        [a.strip() for a in (company.invoice_bcc or "").split(",") if a.strip()]
        if company
        else []
    )
    context = {
        "matter_name": matter.name if matter else "",
        "matter_number": matter.id if matter else "",
        "client_name": client.name if client else "",
        "amount_due": payment_request.amount_requested,
        "cover_message": message or "",
        "firm_name": company.name if company else "",
        "firm_email": company.email if company else "",
        "pay_url": request_pay_url(payment_request, request),
    }
    subject = "Payment request"
    if matter:
        subject += f" — Matter {matter.id}"

    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=render_to_string("emails/payment_request_email.txt", context),
            from_email=None,  # falls back to DEFAULT_FROM_EMAIL
            to=[to],
            bcc=bcc_list or None,
            reply_to=[company.email] if company and company.email else None,
        )
        email.attach_alternative(
            render_inlined("emails/payment_request_email.html", context), "text/html"
        )
        # Attach the matter ledger statement (current account activity + balance).
        pdf_tmp = generate_ledger(matter.id, request)
        try:
            with open(pdf_tmp.name, "rb") as f:
                email.attach(
                    f"statement_matter_{matter.id}.pdf", f.read(), "application/pdf"
                )
        finally:
            os.unlink(pdf_tmp.name)
        email.send()
    except Exception as exc:
        raise PaymentRequestSendError(
            f"Could not send the payment request: {exc}"
        ) from exc
    return True
