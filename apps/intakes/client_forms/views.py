"""Staff-facing views for custom intake forms: the template library, the
builder, and the per-intake send/review panel.

All of these live under `/intakes/`, so `PermissionMiddleware` gates them on
`perm_intakes` and each view only needs `@login_required`. The public,
no-login side is `client_forms/public_views.py`.
"""

import copy
import json
import uuid

from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.intakes.client_forms.forms import (
    FormTemplateForm,
    ResendFormForm,
    SendFormForm,
)
from apps.intakes.client_forms.links import form_url
from apps.intakes.client_forms.models import (
    FormSubmission,
    FormTemplate,
    submissions_for_intake,
)
from apps.intakes.client_forms.render import orphan_answers, render_blocks
from apps.intakes.client_forms.schema import (
    MAX_SCHEMA_BYTES,
    SchemaError,
    defaults,
    normalize_schema,
    palette,
)
from apps.intakes.client_forms.send import (
    FormSendError,
    log_transmission,
    send_form_link,
)
from apps.intakes.models import Intake
from utils.toasts import toast_success

FORMS_TRIGGER = "intakeFormsChanged"


def _templates():
    return FormTemplate.objects.annotate(submission_count=Count("submissions"))


def _forms_context(**extra):
    return {"app": "intakes", "subapp": "forms"} | extra


def _refresh(message=None):
    """The 204 + HX-Trigger that makes the templates list re-fetch itself."""
    response = HttpResponse(status=204, headers={"HX-Trigger": FORMS_TRIGGER})
    return toast_success(response, message) if message else response


# --- Template library -------------------------------------------------------


@login_required
def forms_index(request):
    return render(
        request,
        "intakes/forms/main.html",
        _forms_context(templates=_templates()),
    )


@login_required
def forms_list(request):
    return render(
        request,
        "intakes/forms/list.html",
        _forms_context(templates=_templates()),
    )


@login_required
def form_template_new(request):
    """Create a template, then drop straight into the builder — a form with no
    questions is never what anyone wanted."""
    if request.method == "POST":
        form = FormTemplateForm(request.POST, use_required_attribute=False)
        if form.is_valid():
            template = form.save()
            response = HttpResponse(status=204)
            response["HX-Redirect"] = f"/intakes/forms/{template.id}/"
            return response
    else:
        form = FormTemplateForm(use_required_attribute=False)

    return render(
        request,
        "intakes/forms/template-form.html",
        {"form": form, "action": "/intakes/forms/new/", "title": "New Form"},
    )


@login_required
def form_template_settings(request, template_id):
    template = get_object_or_404(FormTemplate, pk=template_id)

    if request.method == "POST":
        form = FormTemplateForm(
            request.POST, instance=template, use_required_attribute=False
        )
        if form.is_valid():
            form.save()
            return _refresh("Form updated")
    else:
        form = FormTemplateForm(instance=template, use_required_attribute=False)

    return render(
        request,
        "intakes/forms/template-form.html",
        {
            "form": form,
            "action": f"/intakes/forms/{template.id}/settings/",
            "title": "Form Settings",
            "template": template,
        },
    )


@login_required
@require_POST
def form_template_duplicate(request, template_id):
    """Copy a template, questions and all. The copy keeps the original's field
    keys, which is harmless — keys only need to be unique within one form."""
    template = get_object_or_404(FormTemplate, pk=template_id)
    copy_of = FormTemplate.objects.create(
        name=f"{template.name} (copy)"[:120],
        description=template.description,
        intro_text=template.intro_text,
        is_active=False,
        schema=copy.deepcopy(template.schema),
    )
    response = HttpResponse(status=204)
    response["HX-Redirect"] = f"/intakes/forms/{copy_of.id}/"
    return response


@login_required
@require_POST
def form_template_delete(request, template_id):
    """Delete a template. Submissions already sent from it survive — they carry
    their own snapshot and only lose the FK (SET_NULL)."""
    template = get_object_or_404(FormTemplate, pk=template_id)
    template.delete()
    response = HttpResponse(status=204)
    response["HX-Redirect"] = "/intakes/forms/"
    return response


# --- Builder ----------------------------------------------------------------


@login_required
def form_builder(request, template_id):
    template = get_object_or_404(FormTemplate, pk=template_id)
    config = {
        "name": template.name,
        "schema": template.schema or [],
        "palette": palette(),
        "defaults": defaults(),
        "saveUrl": f"/intakes/forms/{template.id}/save/",
    }
    return render(
        request,
        "intakes/forms/builder.html",
        _forms_context(template=template, config=json.dumps(config)),
    )


@login_required
@require_POST
def form_builder_save(request, template_id):
    """Store the whole schema in one POST.

    The response echoes the normalized schema back, and the builder must
    re-hydrate from it: the server mints the field keys, and every future
    submission's answers are filed under them.
    """
    template = get_object_or_404(FormTemplate, pk=template_id)

    if len(request.body) > MAX_SCHEMA_BYTES:
        return JsonResponse(
            {"ok": False, "error": "This form is too large."}, status=413
        )
    try:
        body = json.loads(request.body or "{}")
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "error": "Malformed request."}, status=400)

    try:
        schema = normalize_schema(body.get("schema"))
    except SchemaError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    name = str(body.get("name") or "").strip()[:120]
    if name:
        template.name = name
    template.schema = schema
    template.version += 1
    template.save()

    return JsonResponse(
        {
            "ok": True,
            "schema": schema,
            "version": template.version,
            "saved_at": timezone.localtime(template.updated_at).strftime("%-I:%M %p"),
        }
    )


# --- Sending a form from an intake -----------------------------------------


@login_required
def intake_forms_panel(request, id):
    intake = get_object_or_404(Intake, pk=id)
    return render(
        request,
        "intakes/forms/panel.html",
        {"intake": intake, "submissions": submissions_for_intake(intake)},
    )


@login_required
def intake_form_send(request, id):
    """Create a submission from a template and hand out its link.

    The snapshot is taken here, once, and never rewritten — it is what makes
    the answers mean the same thing in five years.
    """
    intake = get_object_or_404(Intake, pk=id)
    context = {"intake": intake, "action": f"/intakes/{intake.id}/forms/send/"}

    if request.method != "POST":
        form = SendFormForm(initial={"to": intake.email or ""})
        return render(request, "intakes/forms/send.html", context | {"form": form})

    form = SendFormForm(request.POST)
    if not form.is_valid():
        return render(request, "intakes/forms/send.html", context | {"form": form})

    template = form.cleaned_data["template"]
    submission = FormSubmission.objects.create(
        intake=intake,
        template=template,
        template_name=template.name,
        template_version=template.version,
        # Deep copy, not a reference — a later edit to template.schema must not
        # reach back into what was sent.
        schema_snapshot=copy.deepcopy(template.schema),
        recipient_email=form.cleaned_data["to"].strip(),
    )

    if request.POST.get("action") == "link":
        log_transmission(submission, kind="link", status="sent", sent_by=request.user)
        response = render(
            request,
            "intakes/forms/link.html",
            {
                "submission": submission,
                "form_url": form_url(submission, request),
                "intake": intake,
            },
        )
        # Refresh the card behind the modal without closing it (HTMX only
        # auto-closes on a 204).
        response["HX-Trigger"] = FORMS_TRIGGER
        return response

    try:
        send_form_link(
            submission,
            to=form.cleaned_data["to"],
            cc=form.cleaned_data["cc"],
            message=form.cleaned_data["message"],
            sent_by=request.user,
            request=request,
        )
    except FormSendError as exc:
        return render(
            request,
            "intakes/forms/send.html",
            context | {"form": form, "send_error": str(exc)},
        )

    return _refresh(f"Form sent to {submission.recipient_email}")


@login_required
def form_submission_link(request, sub_id):
    """Show the link for a submission that was already created."""
    submission = get_object_or_404(FormSubmission, pk=sub_id)
    if request.method == "POST":
        log_transmission(submission, kind="link", status="sent", sent_by=request.user)
    return render(
        request,
        "intakes/forms/link.html",
        {
            "submission": submission,
            "form_url": form_url(submission, request),
            "intake": submission.intake,
        },
    )


@login_required
def form_submission_resend(request, sub_id):
    submission = get_object_or_404(FormSubmission, pk=sub_id)
    context = {
        "submission": submission,
        "action": f"/intakes/forms/submissions/{submission.id}/resend/",
    }

    if request.method != "POST":
        form = ResendFormForm(initial={"to": submission.recipient_email})
        return render(request, "intakes/forms/resend.html", context | {"form": form})

    form = ResendFormForm(request.POST)
    if not form.is_valid():
        return render(request, "intakes/forms/resend.html", context | {"form": form})

    try:
        send_form_link(
            submission,
            to=form.cleaned_data["to"],
            cc=form.cleaned_data["cc"],
            message=form.cleaned_data["message"],
            sent_by=request.user,
            request=request,
            kind="reminder",
        )
    except FormSendError as exc:
        return render(
            request,
            "intakes/forms/resend.html",
            context | {"form": form, "send_error": str(exc)},
        )

    return _refresh("Reminder sent")


# --- Reviewing what came back ----------------------------------------------


@login_required
def form_submission_review(request, sub_id):
    submission = get_object_or_404(
        FormSubmission.objects.select_related("template", "intake"), pk=sub_id
    )
    return render(
        request,
        "intakes/forms/review.html",
        {
            "submission": submission,
            "blocks": render_blocks(submission.schema_snapshot, submission.answers),
            "orphans": orphan_answers(submission.schema_snapshot, submission.answers),
        },
    )


# Staff actions and the timestamp each one stamps. Anything not listed here is
# not a transition staff can drive.
_STATUS_ACTIONS = {
    "close": ("CLOSED", "closed_at", "Form closed"),
    "reopen": ("SUBMITTED", None, "Form reopened"),
    "cancel": ("CANCELED", None, "Form canceled"),
}


@login_required
@require_POST
def form_submission_status(request, sub_id, status):
    submission = get_object_or_404(FormSubmission, pk=sub_id)
    action = _STATUS_ACTIONS.get(status)
    if action is None:
        return HttpResponse(status=400)

    new_status, stamp, message = action
    submission.status = new_status
    submission.closed_at = timezone.now() if stamp == "closed_at" else None
    submission.save(update_fields=["status", "closed_at", "updated_at"])
    return _refresh(message)


@login_required
@require_POST
def form_submission_revoke(request, sub_id):
    """Rotate the uuid, which invalidates every link already handed out. Staff
    must resend afterwards — that is the point."""
    submission = get_object_or_404(FormSubmission, pk=sub_id)
    submission.uuid = uuid.uuid4()
    submission.save(update_fields=["uuid", "updated_at"])
    return _refresh("Link revoked — send a new one when you're ready")
