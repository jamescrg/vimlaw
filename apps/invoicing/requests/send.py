"""Send a payment request: email the catch-up pay link + the matter ledger
statement to the client. Mirrors apps.invoicing.invoices.functions.send_invoice.
"""

import os

from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.template.loader import render_to_string
from django.utils import timezone

from apps.invoicing.invoices.functions.generate_invoice import store_invoice_pdf
from apps.invoicing.invoices.models import InvoiceTransmission
from apps.invoicing.pay.balance import matter_open_invoices
from apps.invoicing.pay.links import request_pay_url
from apps.invoicing.requests.models import PaymentRequestTransmission
from apps.matters.ledger.generate_ledger import generate_ledger
from apps.settings.models import Firm
from utils.mail import billing_from_email, billing_reply_to, render_inlined


class PaymentRequestSendError(Exception):
    pass


def _log(
    payment_request,
    *,
    to_email,
    cc_email,
    sent_by,
    status,
    error="",
    when=None,
    kind="request",
):
    PaymentRequestTransmission.objects.create(
        payment_request=payment_request,
        kind=kind,
        sent_at=when or timezone.now(),
        to_email=to_email or "",
        cc_email=cc_email or "",
        sent_by=sent_by,
        status=status,
        error=error or "",
    )


def days_since_requested(payment_request):
    """Whole days since the request was last actually emailed (the latest
    successful request-kind transmission, falling back to created_at —
    requests are emailed at creation). Reminders don't reset the clock."""
    last = (
        payment_request.transmissions.filter(kind="request", status="sent")
        .order_by("-sent_at")
        .values_list("sent_at", flat=True)
        .first()
    ) or payment_request.created_at
    if not last:
        return None
    return max((timezone.now() - last).days, 0)


def _parse_recipients(raw):
    """Split a comma/semicolon-delimited address string into a clean list."""
    if not raw:
        return []
    return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]


def _invalid_addresses(addresses):
    invalid = []
    for addr in addresses:
        try:
            validate_email(addr)
        except ValidationError:
            invalid.append(addr)
    return invalid


def send_payment_request(
    payment_request,
    *,
    to=None,
    cc=None,
    message=None,
    attach_statement=True,
    attach_invoices=False,
    sent_by=None,
    request=None,
):
    """Email the request's pay link, optionally with attachments.

    to / cc: comma-delimited address strings; `to` defaults to the request's
    stored recipient(s). message: optional cover note. attach_statement: attach
    the matter ledger statement PDF (and mention it in the body).
    attach_invoices: attach a PDF copy of each of the matter's unpaid invoices —
    each attached invoice also gets a request-kind InvoiceTransmission, so its
    ×N send tally and history reflect the delivery.
    Returns True; raises PaymentRequestSendError on a bad/empty address list or
    send failure. Every attempt is logged as a PaymentRequestTransmission.
    """
    is_trust = payment_request.is_trust
    matter = None if is_trust else payment_request.matter
    client = payment_request.client if is_trust else (matter.client if matter else None)
    if is_trust:
        # Trust requests are client-level with no matter → no statement/invoices.
        attach_statement = attach_invoices = False

    to_list = _parse_recipients(to) or _parse_recipients(
        payment_request.recipient_email
    )
    cc_list = _parse_recipients(cc)
    to_joined = ", ".join(to_list)
    cc_joined = ", ".join(cc_list)
    if not to_list:
        _log(
            payment_request,
            to_email="",
            cc_email=cc_joined,
            sent_by=sent_by,
            status="failed",
            error="No recipient email address.",
        )
        raise PaymentRequestSendError("Enter at least one recipient email address.")
    invalid = _invalid_addresses(to_list + cc_list)
    if invalid:
        error = f"Invalid email address(es): {', '.join(invalid)}"
        _log(
            payment_request,
            to_email=to_joined,
            cc_email=cc_joined,
            sent_by=sent_by,
            status="failed",
            error=error,
        )
        raise PaymentRequestSendError(error)

    company = Firm.objects.first()
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
        "attach_statement": attach_statement,
        "attach_invoices": attach_invoices,
        "is_trust": is_trust,
    }
    firm = company.name if company else ""
    subject = f"{firm} - " if firm else ""
    subject += "Trust Deposit Request" if is_trust else "Payment Request"

    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=render_to_string("emails/payment_request_email.txt", context),
            from_email=billing_from_email(company),  # "<Firm>" <billing addr>
            to=to_list,
            cc=cc_list or None,
            bcc=bcc_list or None,
            # "<Firm> Billing" <billing addr> so replies capture a named contact.
            reply_to=([r] if (r := billing_reply_to(company)) else None),
        )
        email.attach_alternative(
            render_inlined("emails/payment_request_email.html", context), "text/html"
        )
        # Optionally attach the matter ledger statement (account activity + balance).
        if attach_statement:
            pdf_tmp = generate_ledger(matter.id, request)
            filename = f"Matter Ledger {matter.id} {timezone.localdate():%Y-%m-%d}.pdf"
            try:
                with open(pdf_tmp.name, "rb") as f:
                    email.attach(filename, f.read(), "application/pdf")
            finally:
                os.unlink(pdf_tmp.name)
        # Optionally attach a PDF copy of each unpaid invoice.
        attached_invoices = []
        if attach_invoices:
            for inv in matter_open_invoices(matter):
                if not inv.pdf_file:
                    store_invoice_pdf(inv, request)
                with inv.pdf_file.open("rb") as f:
                    email.attach(f"Invoice {inv.id}.pdf", f.read(), "application/pdf")
                attached_invoices.append(inv)
        email.send()
    except PaymentRequestSendError:
        raise
    except Exception as exc:
        _log(
            payment_request,
            to_email=to_joined,
            cc_email=cc_joined,
            sent_by=sent_by,
            status="failed",
            error=str(exc),
        )
        raise PaymentRequestSendError(
            f"Could not send the payment request: {exc}"
        ) from exc

    now = timezone.now()
    _log(
        payment_request,
        to_email=to_joined,
        cc_email=cc_joined,
        sent_by=sent_by,
        status="sent",
        when=now,
    )
    # Each invoice that rode along was delivered to the client — log a
    # request-kind transmission (with request provenance) so its ×N tally and
    # history reflect it, and so later reminders know which invoices this
    # request concerns.
    for inv in attached_invoices:
        InvoiceTransmission.objects.create(
            invoice=inv,
            kind="request",
            payment_request=payment_request,
            sent_at=now,
            to_email=to_joined,
            cc_email=cc_joined,
            sent_by=sent_by,
            status="sent",
        )
    return True


def send_request_reminder(
    payment_request, *, to=None, cc=None, message=None, sent_by=None, request=None
):
    """Email a payment reminder for an already-sent request. Returns True.

    The reminder notes how many days ago the request went out and (for
    operating requests) that payment is due upon receipt under the
    attorney-client agreement; trust reminders use softer retainer language.
    Includes the same pay link, no attachments. Logs a reminder-kind
    transmission on the request AND on each invoice the request's earlier
    sends attached (the reminder concerns those invoices); the days-since
    clocks are untouched.
    """
    is_trust = payment_request.is_trust
    matter = None if is_trust else payment_request.matter
    client = payment_request.client if is_trust else (matter.client if matter else None)

    to_list = _parse_recipients(to) or _parse_recipients(
        payment_request.recipient_email
    )
    cc_list = _parse_recipients(cc)
    to_joined = ", ".join(to_list)
    cc_joined = ", ".join(cc_list)
    if not to_list:
        _log(
            payment_request,
            to_email="",
            cc_email=cc_joined,
            sent_by=sent_by,
            status="failed",
            error="No recipient email address.",
            kind="reminder",
        )
        raise PaymentRequestSendError("Enter at least one recipient email address.")
    invalid = _invalid_addresses(to_list + cc_list)
    if invalid:
        error = f"Invalid email address(es): {', '.join(invalid)}"
        _log(
            payment_request,
            to_email=to_joined,
            cc_email=cc_joined,
            sent_by=sent_by,
            status="failed",
            error=error,
            kind="reminder",
        )
        raise PaymentRequestSendError(error)

    company = Firm.objects.first()
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
        "days_since": days_since_requested(payment_request),
        "firm_name": company.name if company else "",
        "firm_email": company.email if company else "",
        "pay_url": request_pay_url(payment_request, request),
        "is_trust": is_trust,
    }
    firm = company.name if company else ""
    subject = f"{firm} - " if firm else ""
    subject += "Trust Deposit Reminder" if is_trust else "Payment Reminder"

    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=render_to_string("emails/payment_request_reminder_email.txt", context),
            from_email=billing_from_email(company),
            to=to_list,
            cc=cc_list or None,
            bcc=bcc_list or None,
            reply_to=([r] if (r := billing_reply_to(company)) else None),
        )
        email.attach_alternative(
            render_inlined("emails/payment_request_reminder_email.html", context),
            "text/html",
        )
        email.send()
    except Exception as exc:
        _log(
            payment_request,
            to_email=to_joined,
            cc_email=cc_joined,
            sent_by=sent_by,
            status="failed",
            error=str(exc),
            kind="reminder",
        )
        raise PaymentRequestSendError(f"Could not send the reminder: {exc}") from exc

    now = timezone.now()
    _log(
        payment_request,
        to_email=to_joined,
        cc_email=cc_joined,
        sent_by=sent_by,
        status="sent",
        kind="reminder",
        when=now,
    )
    # The reminder concerns the invoices this request's sends delivered — log
    # a reminder against each so their ×N tallies and histories reflect it.
    attached_invoice_ids = (
        payment_request.invoice_transmissions.filter(kind="request", status="sent")
        .values_list("invoice_id", flat=True)
        .distinct()
    )
    for invoice_id in attached_invoice_ids:
        InvoiceTransmission.objects.create(
            invoice_id=invoice_id,
            kind="reminder",
            payment_request=payment_request,
            sent_at=now,
            to_email=to_joined,
            cc_email=cc_joined,
            sent_by=sent_by,
            status="sent",
        )
    return True
