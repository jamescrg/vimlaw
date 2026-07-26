"""The public, no-login page a prospective client fills in.

Access is gated by the signed, expiring token in the URL (see `utils.signing`),
not a session — the token *is* the credential, exactly as on the invoice pay
page. Everything rendered here comes from the submission's `schema_snapshot`,
never the live template, so the client sees the form that was actually sent.

Answers autosave as they type. The save endpoint merges per key rather than
replacing the document, so a page-hide save racing a debounced one cannot wipe
an answer neither of them mentioned.
"""

import json

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.intakes.client_forms.models import FormSubmission
from apps.intakes.client_forms.render import render_blocks
from apps.intakes.client_forms.schema import MAX_ANSWERS_BYTES, validate_answers
from apps.intakes.models import Note
from utils.ratelimit import rate_limited
from utils.signing import read_form_token


def _resolve(token):
    """Return the submission for a signed token, or raise Http404 with a reason
    the 'link unavailable' page can speak to."""
    try:
        submission_uuid = read_form_token(
            token, max_age=settings.INTAKE_FORM_LINK_MAX_AGE
        )
    except signing.SignatureExpired:
        raise Http404("expired")
    except signing.BadSignature:
        raise Http404("invalid")
    return get_object_or_404(
        FormSubmission.objects.select_related("intake"), uuid=submission_uuid
    )


def _unavailable(request, reason, *, status):
    return render(
        request,
        "intakes/forms/public/unavailable.html",
        {"reason": reason},
        status=status,
    )


def _unavailable_for(request, exc):
    if str(exc) == "expired":
        return _unavailable(
            request,
            "This link has expired. Please contact us and we'll send you a new one.",
            status=410,
        )
    return _unavailable(request, "This link is invalid.", status=404)


def form_page(request, token):
    if rate_limited(request, "intake-form-page", limit=60, window=300):
        return _unavailable(
            request,
            "Too many requests. Please wait a moment and try again.",
            status=429,
        )
    try:
        submission = _resolve(token)
    except Http404 as exc:
        return _unavailable_for(request, exc)

    if submission.status == "CANCELED":
        return _unavailable(
            request, "This form is no longer active. Please contact us.", status=410
        )

    # First open is worth knowing about — it distinguishes "never saw it" from
    # "saw it and didn't answer". A draft counts: if the client is looking at
    # it, staff handed the link over somehow, and the row shouldn't go on
    # claiming it was never sent.
    if submission.status in ("DRAFT", "SENT"):
        submission.status = "OPENED"
        submission.opened_at = timezone.now()
        submission.save(update_fields=["status", "opened_at", "updated_at"])

    from apps.settings.models import Firm

    company = Firm.objects.first()
    editable = submission.status != "CLOSED"
    context = {
        "submission": submission,
        "blocks": render_blocks(submission.schema_snapshot, submission.answers),
        "firm_name": company.name if company else "",
        # Signed media URL, minted per render — fine on a page, never in email.
        "logo_url": company.logo.url if company and company.logo else "",
        "firm_email": (company.email if company else "") or "",
        "editable": editable,
        "config": json.dumps(
            {
                "answers": submission.answers or {},
                "saveUrl": f"/form/{token}/save/",
                "submitUrl": f"/form/{token}/submit/",
                "submitted": submission.status in ("SUBMITTED", "CLOSED"),
                "editable": editable,
            }
        ),
    }
    return render(request, "intakes/forms/public/fill.html", context)


def _reject(reason, status):
    return JsonResponse({"ok": False, "error": reason}, status=status)


def _guard(request, token, *, scope, limit):
    """Shared preamble for the two write endpoints. Returns (submission, body)
    or (None, error_response)."""
    if rate_limited(request, scope, limit=limit, window=300):
        return None, _reject("Too many requests. Please wait a moment.", 429)
    # Checked before json.loads so an oversized payload is never parsed.
    if len(request.body) > MAX_ANSWERS_BYTES:
        return None, _reject("That's more than this form can hold.", 413)
    try:
        submission = _resolve(token)
    except Http404 as exc:
        return None, _reject(str(exc), 410)
    if not submission.is_fillable:
        return None, _reject("This form is closed.", 409)
    try:
        body = json.loads(request.body or "{}")
    except (ValueError, TypeError):
        return None, _reject("Malformed request.", 400)
    if not isinstance(body.get("answers"), dict):
        return None, _reject("Malformed request.", 400)
    return submission, body


@require_POST
def form_save(request, token):
    """Autosave. Merges the incoming answers into what's stored rather than
    replacing it, so a partial payload never wipes a key it didn't mention."""
    submission, body = _guard(request, token, scope="intake-form-save", limit=120)
    if submission is None:
        return body

    with transaction.atomic():
        row = FormSubmission.objects.select_for_update().get(pk=submission.pk)
        cleaned, _errors = validate_answers(
            row.schema_snapshot, body["answers"], partial=True
        )
        answers = dict(row.answers or {})
        answers.update(cleaned)
        row.answers = answers
        row.last_saved_at = timezone.now()
        # Autosave shouldn't write a simple_history row per keystroke batch.
        row.skip_history_when_saving = True
        row.save(update_fields=["answers", "last_saved_at", "updated_at"])

    return JsonResponse(
        {
            "ok": True,
            "saved_at": timezone.localtime(row.last_saved_at).strftime("%-I:%M %p"),
        }
    )


@require_POST
def form_submit(request, token):
    """Final submit: validate the whole merged document, then file the
    timeline note on the intake."""
    submission, body = _guard(request, token, scope="intake-form-submit", limit=20)
    if submission is None:
        return body

    with transaction.atomic():
        row = FormSubmission.objects.select_for_update().get(pk=submission.pk)
        # Validate the raw merge, not a pre-cleaned one: an answer that fails
        # coercion has to reach the validator to earn its real message ("Enter
        # a valid email address") instead of being dropped and then reported as
        # missing. Required checks see the whole document, so an answer given
        # in an earlier session still counts.
        merged = dict(row.answers or {}) | body["answers"]
        cleaned, errors = validate_answers(row.schema_snapshot, merged, partial=False)
        # `cleaned` holds everything that coerced, so storing it on the error
        # path keeps the client's other answers; only the offending value is
        # left out, and their browser still shows it.
        row.answers = cleaned
        row.last_saved_at = timezone.now()
        if errors:
            row.skip_history_when_saving = True
            row.save(update_fields=["answers", "last_saved_at", "updated_at"])
            return JsonResponse({"ok": False, "errors": errors}, status=400)

        first_submission = row.status != "SUBMITTED"
        row.status = "SUBMITTED"
        row.submitted_at = timezone.now()
        if first_submission and row.note_id is None:
            row.note = _file_note(row)
        row.save(
            update_fields=[
                "answers",
                "last_saved_at",
                "status",
                "submitted_at",
                "note",
                "updated_at",
            ]
        )

    return JsonResponse({"ok": True})


def _file_note(submission):
    """Drop a breadcrumb in the intake's note timeline so the staff badge lights
    up.

    The text is FIXED. Note.details is run through markdown and emitted with
    |safe on the intake detail page, so routing a client's own words through it
    would be a stored-XSS hole. The answers are read in the forms card, which
    escapes.
    """
    now = timezone.localtime()
    return Note.objects.create(
        intake=submission.intake,
        user=None,
        type="Client Form",
        date=now.date(),
        time=now.time(),
        details=f"Submitted the intake form: {submission.template_name}",
    )
