"""Sending a template email to an intake.

The three-dot menu on the intake detail opens a modal: pick a template
(subject/body fill in, editable per send - templates carry no merge
fields, so the salutation is hand-tweaked here), then send. The send is
plain text, From the firm's name, Reply-To (and Cc) the firm's intake
inbox, and is recorded as an "Email Out" note tagged to the sending user.
"""

import logging

from django.contrib.auth.decorators import login_required
from django.core.mail import EmailMessage
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.intakes.models import Intake, IntakeEmailTemplate, Note
from apps.settings.models import Firm
from utils.mail import firm_from_email, intake_reply_to
from utils.toasts import toast_success

logger = logging.getLogger(__name__)


def _modal_context(intake, **extra):
    return {
        "intake": intake,
        "email_templates": IntakeEmailTemplate.objects.all(),
        "template_map": {
            str(t.id): {"subject": t.subject, "body": t.body}
            for t in IntakeEmailTemplate.objects.all()
        },
    } | extra


@login_required
def send_email_modal(request, id):
    intake = get_object_or_404(Intake, pk=id)
    return render(request, "intakes/send-email.html", _modal_context(intake))


@login_required
@require_http_methods(["POST"])
def send_email(request, id):
    intake = get_object_or_404(Intake, pk=id)
    subject = request.POST.get("subject", "").strip()
    body = request.POST.get("body", "").strip()

    error = None
    if not intake.email:
        error = "This intake has no email address."
    elif not subject or not body:
        error = "Subject and body are both required."

    if error is None:
        company = Firm.objects.first()
        reply_to = intake_reply_to(company)
        cc = (company.intake_email or "").strip() if company else ""
        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=firm_from_email(company),
            to=[intake.email],
            cc=[cc] if cc else None,
            reply_to=[reply_to] if reply_to else None,
        )
        try:
            email.send()
        except Exception as exc:
            logger.exception("Intake email send failed")
            error = f"Send failed: {exc}"

    if error is not None:
        return render(
            request,
            "intakes/send-email.html",
            _modal_context(intake, error=error, subject=subject, body=body),
        )

    now = timezone.localtime()
    Note.objects.create(
        intake=intake,
        user=request.user,
        date=now.date(),
        time=now.time(),
        type="Email Out",
        details=f"**Subject:** {subject}\n\n{body}",
    )
    response = HttpResponse(status=204, headers={"HX-Trigger": "intakeDetailChanged"})
    toast_success(response, "Email sent")
    return response
