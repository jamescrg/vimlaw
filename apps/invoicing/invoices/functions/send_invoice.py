"""Email an invoice PDF to the client and record the transmission.

Replaces the manual LawPay "QuickBill" send. On success the invoice is marked
SENT (with date_sent) and a 'sent' InvoiceTransmission row is written; on failure
a 'failed' row is logged and InvoiceSendError is raised with the status left
unchanged.
"""

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from apps.invoicing.invoices.functions.generate_invoice import store_invoice_pdf
from apps.invoicing.invoices.models import InvoiceTransmission


class InvoiceSendError(Exception):
    """Raised when an invoice could not be emailed (recipient missing, SMTP
    failure, PDF generation error). The invoice status is left unchanged."""


def _log(invoice, *, to_email, cc_email, sent_by, status, error="", when=None):
    InvoiceTransmission.objects.create(
        invoice=invoice,
        sent_at=when or timezone.now(),
        to_email=to_email or "",
        cc_email=cc_email or "",
        sent_by=sent_by,
        status=status,
        error=error or "",
    )


def send_invoice(
    invoice, *, to=None, cc=None, message=None, sent_by=None, request=None
):
    """Send `invoice` to the client. Returns True on success.

    to / cc: override recipient(s); default recipient is the matter client email.
    message: cover-note override; defaults to the invoice's own `message`.
    """
    matter = invoice.matter
    client = matter.client if matter else None
    to_email = (to or (client.email if client else "") or "").strip()
    cc_email = (cc or "").strip()

    if not to_email:
        _log(
            invoice,
            to_email="",
            cc_email=cc_email,
            sent_by=sent_by,
            status="failed",
            error="No client email address on file.",
        )
        raise InvoiceSendError("This matter's client has no email address on file.")

    try:
        # Always regenerate so the attached PDF reflects the invoice's current
        # state (it may have been edited since the last APPROVED/SENT render).
        store_invoice_pdf(invoice, request)

        cover = message if message is not None else (invoice.message or "")
        context = {
            "invoice": invoice,
            "matter_name": matter.name if matter else "",
            "client_name": client.name if client else "",
            "amount_due": invoice.amount_remaining,
            "cover_message": cover,
            "firm_name": getattr(settings, "FIRM_NAME", ""),
            "pay_url": None,  # Phase 2: tokenized online-payment link
        }
        subject = f"Invoice #{invoice.id}"
        if matter:
            subject += f" — {matter.name}"

        email = EmailMultiAlternatives(
            subject=subject,
            body=render_to_string("emails/invoice_email.txt", context),
            from_email=None,  # falls back to DEFAULT_FROM_EMAIL
            to=[to_email],
            cc=[cc_email] if cc_email else [],
        )
        email.attach_alternative(
            render_to_string("emails/invoice_email.html", context), "text/html"
        )
        with invoice.pdf_file.open("rb") as f:
            email.attach(f"invoice_{invoice.id}.pdf", f.read(), "application/pdf")
        email.send()
    except Exception as exc:
        _log(
            invoice,
            to_email=to_email,
            cc_email=cc_email,
            sent_by=sent_by,
            status="failed",
            error=str(exc),
        )
        raise InvoiceSendError(f"Could not send the invoice: {exc}") from exc

    now = timezone.now()
    invoice.status = "SENT"
    invoice.date_sent = now
    invoice.save(update_fields=["status", "date_sent"])
    _log(
        invoice,
        to_email=to_email,
        cc_email=cc_email,
        sent_by=sent_by,
        status="sent",
        when=now,
    )
    return True
