"""Email an invoice PDF to the client and record the transmission.

Replaces the manual LawPay "QuickBill" send. On success the invoice is marked
SENT (with date_sent) and a 'sent' InvoiceTransmission row is written; on failure
a 'failed' row is logged and InvoiceSendError is raised with the status left
unchanged.
"""

from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.template.loader import render_to_string
from django.utils import timezone

from apps.invoicing.invoices.functions.generate_invoice import store_invoice_pdf
from apps.invoicing.invoices.models import InvoiceTransmission
from apps.invoicing.pay.links import payment_url
from apps.settings.models import Firm
from utils.mail import billing_from_email, billing_reply_to, render_inlined


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


def _log(
    invoice, *, to_email, cc_email, sent_by, status, error="", when=None, kind="invoice"
):
    InvoiceTransmission.objects.create(
        invoice=invoice,
        kind=kind,
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
        # Firm branding comes from the Firm settings record (same source as
        # the PDF), not a hardcoded setting.
        company = Firm.objects.first()
        bcc_list = _parse_recipients(company.invoice_bcc) if company else []
        # Billing correspondence (client replies + the "contact us" address in
        # the email body) goes to the firm's billing email, falling back to the
        # general firm email when no billing address is configured.
        billing_email = ""
        if company:
            billing_email = company.billing_email or company.email
        context = {
            "invoice": invoice,
            "matter_name": matter.name if matter else "",
            "matter_number": matter.id if matter else "",
            "client_name": client.name if client else "",
            "amount_due": invoice.amount_remaining,
            "cover_message": cover,
            "firm_name": company.name if company else "",
            "billing_email": billing_email,
            "pay_url": payment_url(invoice, request),  # tokenized payment link
        }
        # Client-facing: lead with the firm name, then identify by number (not
        # matter name, which is internal and subject to change). Plain hyphens.
        firm = company.name if company else ""
        subject = f"{firm} - " if firm else ""
        subject += f"Invoice {invoice.id}"
        if matter:
            subject += f" - Matter {matter.id}"

        email = EmailMultiAlternatives(
            subject=subject,
            body=render_to_string("emails/invoice_email.txt", context),
            from_email=billing_from_email(company),  # "<Firm>" <billing addr>
            to=to_list,
            cc=cc_list,
            # Firm archive copy (Firm.invoice_bcc); the BCC'd mailbox retains
            # the full email, cover message and PDF included.
            bcc=bcc_list or None,
            # Client replies go to the firm's billing email (Firm settings),
            # labeled "<Firm> Billing", not the unattended From address.
            reply_to=[billing_reply_to(company)] if billing_email else None,
        )
        email.attach_alternative(
            render_inlined("emails/invoice_email.html", context), "text/html"
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


def days_since_sent(invoice):
    """Whole days since the invoice was last actually emailed (the latest
    successful invoice-kind transmission, falling back to date_sent).
    Reminders don't reset the clock. None when it was never emailed."""
    last = (
        invoice.transmissions.filter(kind="invoice", status="sent")
        .order_by("-sent_at")
        .values_list("sent_at", flat=True)
        .first()
    ) or invoice.date_sent
    if not last:
        return None
    return max((timezone.now() - last).days, 0)


def send_reminder(
    invoice, *, to=None, cc=None, message=None, sent_by=None, request=None
):
    """Email a payment reminder for an already-sent invoice. Returns True.

    The reminder notes how many days ago the invoice went out, that payment is
    due upon receipt under the attorney-client agreement, and that
    accommodations are available on request. It attaches a courtesy copy of
    the invoice PDF and logs a 'reminder'-kind transmission; the invoice's
    status, date_sent, and ×N send tally are untouched.
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
            kind="reminder",
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
            kind="reminder",
        )
        raise InvoiceSendError(error)

    try:
        if not invoice.pdf_file:
            store_invoice_pdf(invoice, request)

        company = Firm.objects.first()
        bcc_list = _parse_recipients(company.invoice_bcc) if company else []
        billing_email = ""
        if company:
            billing_email = company.billing_email or company.email
        context = {
            "invoice": invoice,
            "matter_name": matter.name if matter else "",
            "matter_number": matter.id if matter else "",
            "client_name": client.name if client else "",
            "amount_due": invoice.amount_remaining,
            "cover_message": message or "",
            "days_since": days_since_sent(invoice),
            "firm_name": company.name if company else "",
            "billing_email": billing_email,
            "pay_url": payment_url(invoice, request),
        }
        firm = company.name if company else ""
        subject = f"{firm} - " if firm else ""
        subject += f"Payment Reminder - Invoice {invoice.id}"
        if matter:
            subject += f" - Matter {matter.id}"

        email = EmailMultiAlternatives(
            subject=subject,
            body=render_to_string("emails/invoice_reminder_email.txt", context),
            from_email=billing_from_email(company),
            to=to_list,
            cc=cc_list,
            bcc=bcc_list or None,
            reply_to=[billing_reply_to(company)] if billing_email else None,
        )
        email.attach_alternative(
            render_inlined("emails/invoice_reminder_email.html", context), "text/html"
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
            kind="reminder",
        )
        raise InvoiceSendError(f"Could not send the reminder: {exc}") from exc

    _log(
        invoice,
        to_email=to_joined,
        cc_email=cc_joined,
        sent_by=sent_by,
        status="sent",
        kind="reminder",
    )
    return True
