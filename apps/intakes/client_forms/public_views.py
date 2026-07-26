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
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.intakes.client_forms.filling import complete, merge_answers, read_answers
from apps.intakes.client_forms.models import FormSubmission
from apps.intakes.client_forms.render import render_blocks
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
    answers, error = read_answers(request)
    if error == "too-large":
        return None, _reject("That's more than this form can hold.", 413)
    try:
        submission = _resolve(token)
    except Http404 as exc:
        return None, _reject(str(exc), 410)
    if not submission.is_fillable:
        return None, _reject("This form is closed.", 409)
    if error:
        return None, _reject("Malformed request.", 400)
    return submission, {"answers": answers}


@require_POST
def form_save(request, token):
    """Autosave."""
    submission, body = _guard(request, token, scope="intake-form-save", limit=120)
    if submission is None:
        return body

    row = merge_answers(submission, body["answers"])
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

    # require_all: the client is answering their own form, so everything
    # marked required has to be there. Staff completing one over the phone are
    # held to a looser rule — see filling.complete.
    errors = complete(submission, body["answers"], require_all=True)
    if errors:
        return JsonResponse({"ok": False, "errors": errors}, status=400)
    return JsonResponse({"ok": True})
