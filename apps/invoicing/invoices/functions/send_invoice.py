"""Email an invoice PDF to the client and record the transmission.

Replaces the manual LawPay "QuickBill" send. On success the invoice is marked
SENT (with date_sent) and a 'sent' InvoiceTransmission row is written; on failure
a 'failed' row is logged and InvoiceSendError is raised with the status left
unchanged.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.template.loader import render_to_string
from django.utils import timezone

from apps.invoicing.invoices.functions.generate_invoice import store_invoice_pdf
from apps.invoicing.invoices.models import InvoiceTransmission
from apps.invoicing.pay.links import payment_url
from apps.settings.models import Company


class InvoiceSendError(Exception):
    """Raised when an invoice could not be emailed (recipient missing, SMTP
    failure, PDF generation error). The invoice status is left unchanged."""


def _parse_recipients(raw):
    """Split a comma/semicolon-separated address string into a clean list."""
    if not raw:
        return []
    return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]


def _invalid_addresses(addresses):
    """Return the subset of `addresses` that aren't valid email addresses."""
    invalid = []
    for addr in addresses:
        try:
            validate_email(addr)
        except ValidationError:
            invalid.append(addr)
    return invalid


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

    to / cc: override recipient(s); each may be a comma-separated list of
    addresses. The default recipient is the matter client's email.
    message: cover-note override; defaults to the invoice's own `message`.
    """
    matter = invoice.matter
    client = matter.client if matter else None
    to_list = _parse_recipients(to)
    if not to_list and client and client.email:
        to_list = [client.email.strip()]
    cc_list = _parse_recipients(cc)
    to_joined = ", ".join(to_list)
    cc_joined = ", ".join(cc_list)

    if not to_list:
        _log(
            invoice,
            to_email="",
            cc_email=cc_joined,
            sent_by=sent_by,
            status="failed",
            error="No client email address on file.",
        )
        raise InvoiceSendError("This matter's client has no email address on file.")

    invalid = _invalid_addresses(to_list + cc_list)
    if invalid:
        error = f"Invalid email address(es): {', '.join(invalid)}"
        _log(
            invoice,
            to_email=to_joined,
            cc_email=cc_joined,
            sent_by=sent_by,
            status="failed",
            error=error,
        )
        raise InvoiceSendError(error)

    try:
        # The PDF is (re)generated on every create / edit / approve, so the
        # stored file is already current — generate here only if it is somehow
        # missing, rather than paying the WeasyPrint cost on every send.
        if not invoice.pdf_file:
            store_invoice_pdf(invoice, request)

        cover = message if message is not None else (invoice.message or "")
        # Firm branding comes from the Company settings record (same source as
        # the PDF), not a hardcoded setting.
        company = Company.objects.first()
        context = {
            "invoice": invoice,
            "matter_name": matter.name if matter else "",
            "matter_number": matter.id if matter else "",
            "client_name": client.name if client else "",
            "amount_due": invoice.amount_remaining,
            "cover_message": cover,
            "firm_name": company.name if company else "",
            "pay_url": payment_url(invoice, request),  # tokenized payment link
            "invoice_admin_email": settings.INVOICE_ADMIN_EMAIL,
        }
        # Client-facing: identify by number, not matter name (which is internal
        # and subject to change).
        subject = f"Invoice {invoice.id}"
        if matter:
            subject += f" — Matter {matter.id}"

        email = EmailMultiAlternatives(
            subject=subject,
            body=render_to_string("emails/invoice_email.txt", context),
            from_email=None,  # falls back to DEFAULT_FROM_EMAIL
            to=to_list,
            cc=cc_list,
            # Firm archive copy (settings.INVOICE_SEND_BCC); the BCC'd mailbox
            # retains the full email, cover message and PDF included.
            bcc=settings.INVOICE_SEND_BCC or None,
            # Client replies go to the invoicing admin, not the unattended From.
            reply_to=(
                [settings.INVOICE_ADMIN_EMAIL] if settings.INVOICE_ADMIN_EMAIL else None
            ),
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
            to_email=to_joined,
            cc_email=cc_joined,
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
        to_email=to_joined,
        cc_email=cc_joined,
        sent_by=sent_by,
        status="sent",
        when=now,
    )
    return True
