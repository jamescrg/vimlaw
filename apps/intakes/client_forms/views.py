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

from apps.intakes.client_forms.filling import (
    complete,
    merge_answers,
    read_answers,
)
from apps.intakes.client_forms.forms import (
    AddFormForm,
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
    presentable,
    type_labels,
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
    """Form templates are firm configuration, so the library and the builder
    render inside the Settings shell — the arrangement checklists already
    uses. The URLs stay under /intakes/, which keeps PermissionMiddleware's
    perm_intakes gate over them."""
    return {"app": "settings", "subapp": "intake-forms"} | extra


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
def form_template_name_edit(request, template_id):
    """Swap the builder's title for an input — the matter work-status pattern."""
    template = get_object_or_404(FormTemplate, pk=template_id)
    return render(request, "intakes/forms/name-edit.html", {"template": template})


@login_required
def form_template_name_update(request, template_id):
    """Save the inline rename and swap the title back; on GET, just render the
    current title. The builder re-fetches this on intakeFormsChanged, which is
    how a rename made in the settings modal reaches the toolbar and preview.

    The name is not in the builder's autosave payload: with a save firing
    every pause in typing, a stale copy there would quietly overwrite a rename
    made anywhere else.
    """
    template = get_object_or_404(FormTemplate, pk=template_id)
    if request.method == "POST":
        name = str(request.POST.get("name") or "").strip()[:120]
        if name and name != template.name:
            template.name = name
            template.save(update_fields=["name", "updated_at"])
    return render(request, "intakes/forms/name.html", {"template": template})


@login_required
@require_POST
def form_template_preview(request, template_id):
    """The real client page, rendered from the schema the builder is holding.

    A POST, not a GET, and the schema rides in the request: the builder's
    latest keystrokes may not have autosaved yet, so a preview that read the
    database would race the save and sometimes show the version from a moment
    ago. Nothing here is stored — the template is untouched.

    Unfinished fields are hidden here exactly as the client page hides them —
    the preview's one job is to show what the client would see, and an
    unlabelled question is not part of that yet.
    """
    template = get_object_or_404(FormTemplate, pk=template_id)

    if len(request.body) > MAX_SCHEMA_BYTES:
        return HttpResponse("This form is too large to preview.", status=413)
    try:
        raw = json.loads(request.POST.get("schema") or "[]")
    except (ValueError, TypeError):
        return HttpResponse("Malformed preview request.", status=400)

    try:
        schema = presentable(normalize_schema(raw))
    except SchemaError as exc:
        return HttpResponse(f"This form cannot be previewed: {exc}", status=400)

    from apps.settings.models import Firm

    company = Firm.objects.first()
    # An unsaved shim, never persisted — just enough submission for fill.html.
    shim = FormSubmission(
        template=template, template_name=template.name, schema_snapshot=schema
    )
    return render(
        request,
        "intakes/forms/public/fill.html",
        {
            "submission": shim,
            "blocks": render_blocks(schema, {}),
            "firm_name": company.name if company else "",
            "logo_url": company.logo.url if company and company.logo else "",
            "firm_email": (company.email if company else "") or "",
            "default_caption": FormTemplate.DEFAULT_CAPTION,
            "editable": True,
            "preview": True,
            "config": json.dumps(
                {
                    "answers": {},
                    "saveUrl": "",
                    "submitUrl": "",
                    "submitted": False,
                    "editable": True,
                    "preview": True,
                }
            ),
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
        "schema": template.schema or [],
        "palette": palette(),
        "labels": type_labels(),
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

    The response echoes the normalized schema back, and the builder adopts the
    keys from it: the server mints them, and every future submission's answers
    are filed under them.

    The schema and nothing else — the name is edited inline against
    `form_template_name_update` and is not accepted here. Two writers for one
    field is how one of them ends up quietly undoing the other, and with
    autosave running that would be a rename followed a second later by an
    autosave carrying the name the page loaded with.

    The builder autosaves, so this is called on a pause in typing rather than
    on a difference — the same document arrives again whenever someone tabs
    away and back, or edits a label and puts it back. A save that normalizes to
    what is already stored therefore returns without moving the version on. Not
    for the sake of the number: `template_drifted` reads it, so a bump with no
    change behind it tells every submission ever sent from this form that the
    questions have changed since.
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

    if schema != template.schema:
        template.schema = schema
        template.version += 1
        template.save(update_fields=["schema", "version", "updated_at"])

    return JsonResponse(
        {
            "ok": True,
            # The stored schema, which on an unchanged save is the one already
            # there — same keys either way, which is all the builder adopts.
            "schema": template.schema,
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
def intake_form_add(request, id):
    """Step one: create the form. Nothing is sent.

    The snapshot is taken here, once, and never rewritten — it is what makes
    the answers mean the same thing in five years. The submission lands as a
    DRAFT; handing it to the client is a separate, deliberate act.
    """
    intake = get_object_or_404(Intake, pk=id)
    context = {"intake": intake, "action": f"/intakes/{intake.id}/forms/add/"}

    if request.method != "POST":
        return render(
            request, "intakes/forms/add.html", context | {"form": AddFormForm()}
        )

    form = AddFormForm(request.POST)
    if not form.is_valid():
        return render(request, "intakes/forms/add.html", context | {"form": form})

    template = form.cleaned_data["template"]
    FormSubmission.objects.create(
        intake=intake,
        template=template,
        template_name=template.name,
        template_version=template.version,
        # Deep copy, not a reference — a later edit to template.schema must not
        # reach back into what was already created.
        schema_snapshot=copy.deepcopy(template.schema),
        recipient_email=intake.email or "",
    )
    return _refresh(f"{template.name} added — send it when you're ready")


@login_required
def form_submission_send(request, sub_id):
    """Step two: hand an existing form to the client, by email or by link."""
    submission = get_object_or_404(
        FormSubmission.objects.select_related("intake"), pk=sub_id
    )
    context = {
        "submission": submission,
        "intake": submission.intake,
        "action": f"/intakes/forms/submissions/{submission.id}/send/",
    }

    if request.method != "POST":
        form = SendFormForm(
            initial={"to": submission.recipient_email or submission.intake.email or ""}
        )
        return render(request, "intakes/forms/send.html", context | {"form": form})

    form = SendFormForm(request.POST)
    if not form.is_valid():
        return render(request, "intakes/forms/send.html", context | {"form": form})

    recipient = form.cleaned_data["to"].strip()

    if request.POST.get("action") == "link":
        # Copying the link IS delivery — the client has it from that moment,
        # so the row must not go on claiming it was never sent.
        submission.recipient_email = recipient
        submission.save(update_fields=["recipient_email", "updated_at"])
        submission.mark_sent()
        log_transmission(submission, kind="link", status="sent", sent_by=request.user)
        response = render(
            request,
            "intakes/forms/link.html",
            {
                "submission": submission,
                "form_url": form_url(submission, request),
                "intake": submission.intake,
            },
        )
        # Refresh the list behind the modal without closing it (HTMX only
        # auto-closes on a 204).
        response["HX-Trigger"] = FORMS_TRIGGER
        return response

    try:
        send_form_link(
            submission,
            to=recipient,
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

    submission.recipient_email = recipient
    submission.save(update_fields=["recipient_email", "updated_at"])
    submission.mark_sent()
    return _refresh(f"Form sent to {recipient}")


@login_required
def form_submission_link(request, sub_id):
    """Show the link for a form that has already been handed over — the quick
    'give me that URL again' path, distinct from the Send step."""
    submission = get_object_or_404(FormSubmission, pk=sub_id)
    if request.method == "POST":
        submission.mark_sent()
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
def form_submission_fill(request, sub_id):
    """The client's own form, opened by staff.

    A paralegal takes most of these down over the phone, so they need the form
    itself rather than a read-only summary of it — the same page, the same
    order, the same wording, so they can read it out as the client hears it.
    It doubles as the way to see what has been answered so far, which is what
    the review modal used to be for.

    Deliberately not the client's link: opening that would stamp `opened_at`
    and flip the row to Opened, and that signal has to keep meaning the client
    looked at it.
    """
    submission = get_object_or_404(
        FormSubmission.objects.select_related("template", "intake"), pk=sub_id
    )
    editable = submission.is_fillable
    return render(
        request,
        "intakes/forms/public/fill.html",
        {
            "submission": submission,
            # The client's form, so the client's filter: unfinished snapshot
            # fields stay hidden here exactly as on the public page.
            "blocks": render_blocks(
                presentable(submission.schema_snapshot), submission.answers
            ),
            "orphans": orphan_answers(submission.schema_snapshot, submission.answers),
            "staff": True,
            "editable": editable,
            "default_caption": FormTemplate.DEFAULT_CAPTION,
            "firm_name": "",
            "logo_url": "",
            "firm_email": "",
            "config": json.dumps(
                {
                    "answers": submission.answers or {},
                    "saveUrl": f"/intakes/forms/submissions/{submission.id}/fill/save/",
                    "submitUrl": (
                        f"/intakes/forms/submissions/{submission.id}/fill/complete/"
                    ),
                    # Staff always land in the form, never on a thank-you: they
                    # are here to work on it, including after it is submitted.
                    "submitted": False,
                    "editable": editable,
                }
            ),
        },
    )


def _staff_answers(request, submission):
    """The posted answers, or an error response. Same shape as the public
    guard, minus the rate limit — this side is already behind a login."""
    if not submission.is_fillable:
        return None, JsonResponse(
            {"ok": False, "error": "This form is closed."}, status=409
        )
    answers, error = read_answers(request)
    if error == "too-large":
        return None, JsonResponse(
            {"ok": False, "error": "That's more than this form can hold."}, status=413
        )
    if error:
        return None, JsonResponse(
            {"ok": False, "error": "Malformed request."}, status=400
        )
    return answers, None


@login_required
@require_POST
def form_submission_fill_save(request, sub_id):
    """Autosave from the staff fill page."""
    submission = get_object_or_404(FormSubmission, pk=sub_id)
    answers, error = _staff_answers(request, submission)
    if error:
        return error

    row = merge_answers(submission, answers)
    return JsonResponse(
        {
            "ok": True,
            "saved_at": timezone.localtime(row.last_saved_at).strftime("%-I:%M %p"),
        }
    )


@login_required
@require_POST
def form_submission_fill_complete(request, sub_id):
    """Mark a form complete from the staff fill page.

    require_all=False: the paralegal is recording what the caller actually
    told them, so a required question the client wouldn't answer must not be
    able to jam the form. It stays unanswered, and the Done count says so.
    """
    submission = get_object_or_404(FormSubmission, pk=sub_id)
    answers, error = _staff_answers(request, submission)
    if error:
        return error

    errors = complete(submission, answers, by=request.user, require_all=False)
    if errors:
        return JsonResponse({"ok": False, "errors": errors}, status=400)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def form_submission_status(request, sub_id, status):
    """Move a form between states from the status dropdown.

    Status is the whole of the lock: CLOSED is what the public save/submit
    guard checks, so there is no separate flag to keep in step.
    """
    submission = get_object_or_404(FormSubmission, pk=sub_id)

    if status == "complete":
        # The same completion the fill page performs, so a form finished on
        # paper and one finished on screen leave the record in one shape —
        # note filed, submitted_at stamped, attributed to whoever did it.
        complete(submission, by=request.user, require_all=False)
        return _refresh("Form marked complete")

    if status == "lock":
        submission.status = "CLOSED"
        submission.closed_at = timezone.now()
        message = "Form locked — the client can no longer edit it"
    elif status == "reopen":
        submission.status = submission.reopened_status
        submission.closed_at = None
        message = "Form reopened for the client"
    elif status == "cancel":
        # Cancelling is what kills the link: form_page 410s a CANCELED form,
        # so the URL stops working without touching the uuid.
        submission.status = "CANCELED"
        submission.closed_at = None
        message = "Form canceled — its link no longer works"
    elif status == "draft":
        submission.status = "DRAFT"
        submission.closed_at = None
        submission.sent_at = None
        message = "Form reverted to draft"
    else:
        return HttpResponse(status=400)

    submission.save(update_fields=["status", "closed_at", "sent_at", "updated_at"])
    return _refresh(message)


@login_required
@require_POST
def form_submission_delete(request, sub_id):
    """Delete a form sent in error.

    Destroys the client's answers along with it, which is why the template
    warns when any have been given — there is no other copy.
    """
    submission = get_object_or_404(FormSubmission, pk=sub_id)
    name = submission.template_name
    submission.delete()
    return _refresh(f"{name} deleted")


@login_required
@require_POST
def form_submission_reissue(request, sub_id):
    """Mint a fresh link by rotating the uuid.

    Every link already handed out stops resolving at once — the token is a
    signature over this uuid, so changing it invalidates them all. Use when a
    link reached the wrong person; cancelling only closes the form, and
    un-cancelling would hand the same URL back.
    """
    submission = get_object_or_404(FormSubmission, pk=sub_id)
    submission.uuid = uuid.uuid4()
    submission.save(update_fields=["uuid", "updated_at"])
    return _refresh("New link issued — the old one no longer works")
