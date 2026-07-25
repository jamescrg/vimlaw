"""Email a client intake form link. Mirrors apps.invoicing.requests.send.

This mail goes to a stranger who may never have heard from us, so it carries
the firm's name and postal address and avoids subject lines that read like
phishing. Nothing is attached — the form lives behind the signed token.
"""

from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.template.loader import render_to_string
from django.utils import timezone

from apps.intakes.client_forms.links import form_url
from apps.intakes.client_forms.models import FormSubmissionTransmission
from apps.settings.models import Firm
from utils.mail import (
    FIRM_LOGO_CID,
    attach_firm_logo,
    firm_from_email,
    firm_postal_address,
    firm_reply_to,
    render_inlined,
)


class FormSendError(Exception):
    pass


def log_transmission(
    submission, *, kind, status, to_email="", cc_email="", sent_by=None, error=""
):
    """Record one delivery attempt — an email, a reminder, or a copied link."""
    return FormSubmissionTransmission.objects.create(
        submission=submission,
        kind=kind,
        sent_at=timezone.now(),
        to_email=to_email or "",
        cc_email=cc_email or "",
        sent_by=sent_by,
        status=status,
        error=error or "",
    )


def _parse_recipients(raw):
    """Split a comma/semicolon-delimited address string into a clean list."""
    if not raw:
        return []
    return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]


def _invalid_addresses(addresses):
    invalid = []
    for address in addresses:
        try:
            validate_email(address)
        except ValidationError:
            invalid.append(address)
    return invalid


def send_form_link(
    submission,
    *,
    to=None,
    cc=None,
    message=None,
    sent_by=None,
    request=None,
    kind="send",
):
    """Email the form's link. Returns True, or raises FormSendError.

    Every attempt is logged as a FormSubmissionTransmission, success or not, so
    the intake's forms card can show what was sent and when.
    """
    to_list = _parse_recipients(to) or _parse_recipients(submission.recipient_email)
    cc_list = _parse_recipients(cc)
    to_joined = ", ".join(to_list)
    cc_joined = ", ".join(cc_list)

    if not to_list:
        log_transmission(
            submission,
            kind=kind,
            status="failed",
            cc_email=cc_joined,
            sent_by=sent_by,
            error="No recipient email address.",
        )
        raise FormSendError("Enter at least one recipient email address.")

    invalid = _invalid_addresses(to_list + cc_list)
    if invalid:
        error = f"Invalid email address(es): {', '.join(invalid)}"
        log_transmission(
            submission,
            kind=kind,
            status="failed",
            to_email=to_joined,
            cc_email=cc_joined,
            sent_by=sent_by,
            error=error,
        )
        raise FormSendError(error)

    company = Firm.objects.first()
    context = {
        "form_name": submission.template_name,
        "client_name": submission.intake.name,
        "cover_message": message or "",
        "question_count": submission.question_count,
        "form_url": form_url(submission, request),
        "firm_name": company.name if company else "",
        "firm_email": (company.email if company else "") or "",
        "firm_phone": (company.phone if company else "") or "",
        "logo_cid": FIRM_LOGO_CID if company and company.logo else "",
        "firm_address": firm_postal_address(company),
        "is_reminder": kind == "reminder",
    }
    firm = company.name if company else ""
    prefix = f"{firm} - " if firm else ""
    # Name the topic, not the ask — see the note in requests/send.py about
    # subject lines that pattern-match as phishing.
    suffix = (
        "A reminder about your intake form"
        if kind == "reminder"
        else "Your intake form"
    )
    template = (
        "intake_form_reminder_email" if kind == "reminder" else "intake_form_email"
    )

    try:
        email = EmailMultiAlternatives(
            subject=f"{prefix}{suffix}",
            body=render_to_string(f"emails/{template}.txt", context),
            from_email=firm_from_email(company),
            to=to_list,
            cc=cc_list or None,
            reply_to=([r] if (r := firm_reply_to(company)) else None),
        )
        email.attach_alternative(
            render_inlined(f"emails/{template}.html", context), "text/html"
        )
        if context["logo_cid"]:
            attach_firm_logo(email, company)
        email.send()
    except Exception as exc:
        log_transmission(
            submission,
            kind=kind,
            status="failed",
            to_email=to_joined,
            cc_email=cc_joined,
            sent_by=sent_by,
            error=str(exc),
        )
        raise FormSendError(f"Could not send the form: {exc}") from exc

    log_transmission(
        submission,
        kind=kind,
        status="sent",
        to_email=to_joined,
        cc_email=cc_joined,
        sent_by=sent_by,
    )
    return True
