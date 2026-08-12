from unittest.mock import patch

import pytest
from django.core.cache import cache

from apps.notes import tasks
from apps.notes.models import Note, NoteFolder

pytestmark = pytest.mark.django_db


@pytest.fixture
def library_note(user):
    folder = NoteFolder.objects.create(name="Research")
    return Note.objects.create(
        author=user,
        title="Adverse Possession",
        folder=folder,
        content="Twenty years of open, notorious possession. " * 20,
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


class TestGenerateNoteSummary:
    def test_generates_and_stores_hash(self, library_note):
        with patch(
            "apps.case.ai.gemini_client.send_to_gemini",
            return_value=("Covers adverse possession requirements.", 10, 5),
        ) as send:
            tasks.generate_note_summary(library_note.id)
        library_note.refresh_from_db()
        assert library_note.summary == "Covers adverse possession requirements."
        assert library_note.summary_source_hash == tasks.summary_hash(
            library_note.content
        )
        assert send.called

    def test_skips_when_hash_current(self, library_note):
        library_note.summary = "Existing"
        library_note.summary_source_hash = tasks.summary_hash(library_note.content)
        library_note.save(update_fields=["summary", "summary_source_hash"])
        with patch("apps.case.ai.gemini_client.send_to_gemini") as send:
            tasks.generate_note_summary(library_note.id)
        assert not send.called

    def test_regenerates_when_content_changed(self, library_note):
        library_note.summary = "Old summary"
        library_note.summary_source_hash = tasks.summary_hash(library_note.content)
        library_note.save(update_fields=["summary", "summary_source_hash"])
        library_note.content = "Completely new content about easements."
        library_note.save(update_fields=["content"])
        with patch(
            "apps.case.ai.gemini_client.send_to_gemini",
            return_value=("New summary.", 10, 5),
        ) as send:
            tasks.generate_note_summary(library_note.id)
        library_note.refresh_from_db()
        assert library_note.summary == "New summary."
        assert send.called

    def test_skips_matter_notes_and_empty(self, user, matter, library_note):
        matter_note = Note.objects.create(
            author=user, matter=matter, title="M", content="text"
        )
        empty = Note.objects.create(author=user, title="Empty", content="")
        with patch("apps.case.ai.gemini_client.send_to_gemini") as send:
            tasks.generate_note_summary(matter_note.id)
            tasks.generate_note_summary(empty.id)
        assert not send.called

    def test_input_capped(self, library_note):
        library_note.content = "x" * (tasks.SUMMARY_TEXT_LIMIT + 5000)
        library_note.save(update_fields=["content"])
        captured = {}

        def fake_send(system_context, messages, model):
            captured["content"] = messages[0]["content"]
            return ("Summary.", 1, 1)

        with patch("apps.case.ai.gemini_client.send_to_gemini", side_effect=fake_send):
            tasks.generate_note_summary(library_note.id)
        # title header + capped excerpt + continuation marker
        assert len(captured["content"]) < tasks.SUMMARY_TEXT_LIMIT + 200
        assert "note continues" in captured["content"]


class TestQueueing:
    def test_queue_note_summary_debounces(self, library_note):
        with patch("django_q.tasks.async_task") as async_task:
            tasks.queue_note_summary(library_note.id)
            tasks.queue_note_summary(library_note.id)
        assert async_task.call_count == 1

    def test_queue_note_summary_queues_any_general_note(self, user):
        loose = Note.objects.create(author=user, title="Loose", content="text")
        with patch("django_q.tasks.async_task") as async_task:
            tasks.queue_note_summary(loose.id)
        assert async_task.called

    def test_queue_note_summary_skips_matter_notes(self, user, matter):
        note = Note.objects.create(
            author=user, title="Case", matter=matter, content="text"
        )
        with patch("django_q.tasks.async_task") as async_task:
            tasks.queue_note_summary(note.id)
        assert not async_task.called

    def test_queue_stale_library_summaries(self, library_note, user):
        current = Note.objects.create(
            author=user,
            title="Current",
            folder=library_note.folder,
            content="settled content",
        )
        current.summary = "Fine"
        current.summary_source_hash = tasks.summary_hash(current.content)
        current.save(update_fields=["summary", "summary_source_hash"])
        with patch("django_q.tasks.async_task") as async_task:
            queued = tasks.queue_stale_library_summaries()
        assert queued == 1
        assert async_task.call_count == 1
        assert async_task.call_args[0][1] == library_note.id
