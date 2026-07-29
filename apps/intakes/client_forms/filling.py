"""The write side of filling a form in.

Two routes reach it: the client's public page, gated by a signed link, and the
staff page a paralegal opens to take the same answers down over the phone.
Both end at the same three operations — merge an autosave, complete the form,
file what was said onto the intake's timeline — so those live here instead of
being written twice and drifting.

What differs between the callers is who is let in, and how strict the final
check is. Not what happens to the data.
"""

import json

from django.db import transaction
from django.utils import timezone

from apps.intakes.client_forms.models import FormSubmission
from apps.intakes.client_forms.render import submission_markdown
from apps.intakes.client_forms.schema import MAX_ANSWERS_BYTES, validate_answers
from apps.intakes.models import Note


def read_answers(request):
    """The posted answer document as (answers, error), error being one of
    "too-large" or "malformed" when there is nothing usable to read."""
    # Checked before json.loads so an oversized payload is never parsed.
    if len(request.body) > MAX_ANSWERS_BYTES:
        return None, "too-large"
    try:
        body = json.loads(request.body or "{}")
    except (ValueError, TypeError):
        return None, "malformed"
    if not isinstance(body.get("answers"), dict):
        return None, "malformed"
    return body["answers"], None


def merge_answers(submission, incoming):
    """Autosave. Merges the incoming answers into what's stored rather than
    replacing it, so a partial payload never wipes a key it didn't mention.

    Returns the row it saved, for its `last_saved_at`.
    """
    with transaction.atomic():
        row = FormSubmission.objects.select_for_update().get(pk=submission.pk)
        cleaned, _errors = validate_answers(row.schema_snapshot, incoming, partial=True)
        answers = dict(row.answers or {})
        answers.update(cleaned)
        row.answers = answers
        row.last_saved_at = timezone.now()
        # Autosave shouldn't write a simple_history row per keystroke batch.
        row.skip_history_when_saving = True
        row.save(update_fields=["answers", "last_saved_at", "updated_at"])
    return row


def complete(submission, incoming=None, *, by=None, require_all=True):
    """Final submit: validate the whole merged document, mark it submitted and
    file the timeline note. Returns a dict of field errors, empty on success.

    `require_all` is the one real difference between the client submitting and
    staff completing. The client has to answer everything marked required.
    Staff are recording what they were actually told, and a caller who won't
    give a middle name shouldn't be able to jam the paralegal — so their
    unanswered questions simply stay unanswered, which the Done count already
    reports. Both paths still coerce, so a malformed email is caught either
    way.
    """
    with transaction.atomic():
        row = FormSubmission.objects.select_for_update().get(pk=submission.pk)
        # Validate the raw merge, not a pre-cleaned one: an answer that fails
        # coercion has to reach the validator to earn its real message ("Enter
        # a valid email address") instead of being dropped and then reported as
        # missing. Required checks see the whole document, so an answer given
        # in an earlier session still counts.
        merged = dict(row.answers or {}) | (incoming or {})
        cleaned, errors = validate_answers(
            row.schema_snapshot, merged, partial=not require_all
        )
        # `cleaned` holds everything that coerced, so storing it on the error
        # path keeps the other answers; only the offending value is left out,
        # and the browser still shows it.
        row.answers = cleaned
        row.last_saved_at = timezone.now()
        if errors:
            row.skip_history_when_saving = True
            row.save(update_fields=["answers", "last_saved_at", "updated_at"])
            return errors

        row.status = "SUBMITTED"
        row.submitted_at = timezone.now()
        file_note(row, by=by)
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
    return {}


def file_note(submission, *, by=None):
    """Put what was said into the intake's note timeline, as Markdown.

    Rewritten on every submit, not just the first. Submitting is not a
    one-shot event here — staff reopen a form, the client comes back and
    answers more — and a note that froze at the first pass would describe a
    file that has since changed. Its date stays at the first submit so the
    timeline keeps its order; that a later pass changed it shows as the note's
    `edited_at`. Nothing is lost either: Note carries HistoricalRecords, so
    each earlier version stays readable.

    `by` is the staff member who took the answers down, and None when the
    client filled the form themselves — so the note is attributed to whoever
    last put words in it.

    Every piece of client text is neutralised on the way in by
    render.submission_markdown — Note.details is rendered through markdown and
    emitted with |safe on the intake page, so an unescaped answer would be
    live HTML there.
    """
    now = timezone.localtime()
    details = submission_markdown(submission)

    if submission.note is None:
        submission.note = Note.objects.create(
            intake=submission.intake,
            user=by,
            type="Client Form",
            date=now.date(),
            time=now.time(),
            details=details,
        )
        return

    submission.note.details = details
    submission.note.user = by
    submission.note.save(update_fields=["details", "user", "updated_at"])
