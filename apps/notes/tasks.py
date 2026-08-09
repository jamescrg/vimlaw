import hashlib
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

NOTE_SUMMARY_PROMPT = (
    "You are summarizing an internal legal reference note from a law firm's "
    "library (a research outline or practice guide). Produce a concise 2-3 "
    "sentence abstract: what topics and legal questions the note covers, the "
    "key rules or conclusions it records, and when a lawyer would consult it. "
    "Be specific about doctrines, statutes, and jurisdictions mentioned."
)

# Maximum characters of note content to send for summarization
SUMMARY_TEXT_LIMIT = 10_000

# Seconds to suppress duplicate queueing for the same note (autosave fires often)
QUEUE_DEBOUNCE_SECONDS = 120


def summary_hash(content):
    """Hash of the content excerpt a summary would be generated from."""
    return hashlib.md5(content[:SUMMARY_TEXT_LIMIT].encode()).hexdigest()


def generate_note_summary(note_id):
    """
    Generate an AI abstract of a library note using Gemini Flash.

    Unlike document summaries (write-once after OCR), notes are living
    documents: the summary regenerates whenever the stored source hash no
    longer matches the content. Safe to over-queue — a matching hash no-ops.
    """
    from apps.case.ai.gemini_client import send_to_gemini
    from apps.notes.models import Note

    try:
        note = Note.objects.get(id=note_id)
    except Note.DoesNotExist:
        logger.error(f"Note {note_id} not found for summary generation")
        return

    if note.matter_id is not None or not note.content:
        return
    if note.summary and note.summary_source_hash == summary_hash(note.content):
        return

    try:
        text_excerpt = note.content[:SUMMARY_TEXT_LIMIT]
        if len(note.content) > SUMMARY_TEXT_LIMIT:
            text_excerpt += "\n... (note continues)"

        response_text, _, _ = send_to_gemini(
            system_context=NOTE_SUMMARY_PROMPT,
            messages=[{"role": "user", "content": f"# {note.title}\n\n{text_excerpt}"}],
            model="gemini-2.5-flash",
        )

        note.summary = response_text.strip()
        note.summary_source_hash = summary_hash(note.content)
        note.save(update_fields=["summary", "summary_source_hash"])

        logger.info(f"Summary generated for note {note_id}: {len(note.summary)} chars")

    except Exception as e:
        logger.warning(f"Summary generation failed for note {note_id}: {e}")


def queue_note_summary(note_id):
    """Queue summary generation for a note if it is a library candidate."""
    from django_q.tasks import async_task

    from apps.notes.models import get_library_notes

    if not cache.add(f"note-summary-queued-{note_id}", 1, QUEUE_DEBOUNCE_SECONDS):
        return
    if not get_library_notes().filter(pk=note_id).exists():
        return
    async_task(
        "apps.notes.tasks.generate_note_summary",
        note_id,
        task_name=f"NoteSummary-{note_id}",
        group="summary_generation",
    )


def queue_stale_library_summaries():
    """Queue regeneration for every library note whose summary is missing or stale.

    Called after a folder's AI-library flag or parent changes, and by the
    backfill management command.
    """
    from django_q.tasks import async_task

    from apps.notes.models import get_library_notes

    queued = 0
    for note in get_library_notes().only(
        "id", "content", "summary", "summary_source_hash"
    ):
        if not note.content:
            continue
        if note.summary and note.summary_source_hash == summary_hash(note.content):
            continue
        async_task(
            "apps.notes.tasks.generate_note_summary",
            note.id,
            task_name=f"NoteSummary-{note.id}",
            group="summary_generation",
        )
        queued += 1
    logger.info(f"Queued {queued} stale library note summaries")
    return queued
