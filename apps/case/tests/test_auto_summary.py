from unittest.mock import patch

import pytest

from apps.case.ai.auto_summary import (
    AUTO_SUMMARY_PROMPT,
    AUTO_SUMMARY_TITLE,
    AUTO_SUMMARY_UPDATE_PROMPT,
    refresh_auto_summaries,
    refresh_matter_auto_summary,
)
from apps.case.ai.models import Conversation, Message
from apps.matters.models import Matter
from apps.notes.models import Note

pytestmark = pytest.mark.django_db


@pytest.fixture
def mock_ai():
    with (
        patch(
            "apps.case.ai.auto_summary.assemble_matter_context_with_selection",
            return_value="FULL CONTEXT",
        ) as assemble,
        patch(
            "apps.case.ai.auto_summary.send_to_gemini",
            return_value=("A fresh summary.", 1000, 200),
        ) as send,
    ):
        send.assemble = assemble
        yield send


class TestDispatcher:
    def test_queues_only_open_matters(self, matter, user, contact, practice_area):
        closed = Matter.objects.create(
            user=user,
            name="Closed Matter",
            status="Closed",
            date_start="2024-01-01",
            practice_area=practice_area,
            client=contact,
        )
        pending = Matter.objects.create(
            user=user,
            name="Pending Matter",
            status="Pending",
            date_start="2024-01-01",
            practice_area=practice_area,
            client=contact,
        )
        with patch("django_q.tasks.async_task") as async_task:
            count = refresh_auto_summaries()

        assert count == 1
        async_task.assert_called_once_with(
            "apps.case.ai.auto_summary.refresh_matter_auto_summary",
            matter.id,
            task_name=f"AutoSummary-{matter.id}",
            group="auto_summary",
        )
        queued_ids = {call.args[1] for call in async_task.call_args_list}
        assert closed.id not in queued_ids
        assert pending.id not in queued_ids


class TestWorker:
    def test_first_run_creates_conversation(self, matter, mock_ai):
        refresh_matter_auto_summary(matter.id)

        conversation = Conversation.objects.get(matter=matter)
        assert conversation.title == AUTO_SUMMARY_TITLE
        assert conversation.llm == "gemini-flash"
        assert conversation.ai_context == "always"
        assert conversation.vet_citations is False
        assert conversation.user is None
        assert conversation.summary == "A fresh summary."

        mock_ai.assemble.assert_called_once()
        assert mock_ai.call_args.kwargs["system_context"] == "FULL CONTEXT"

        messages = list(conversation.messages.all())
        assert [m.role for m in messages] == ["user", "assistant"]
        assert messages[0].content == AUTO_SUMMARY_PROMPT
        assert messages[1].content == "A fresh summary."
        assert messages[1].input_tokens == 1000
        assert messages[1].output_tokens == 200

    def test_second_run_is_incremental_and_replaces_messages(self, matter, mock_ai):
        refresh_matter_auto_summary(matter.id)
        conversation = Conversation.objects.get(matter=matter)
        original_created_at = conversation.created_at

        Note.objects.create(
            matter=matter, title="Deposition prep", content="Key admissions listed."
        )
        old_note = Note.objects.create(
            matter=matter, title="Old strategy memo", content="Stale."
        )
        Note.objects.filter(id=old_note.id).update(updated_at="2020-01-01T00:00:00Z")

        mock_ai.assemble.reset_mock()
        mock_ai.return_value = ("An even fresher summary.", 1100, 210)
        refresh_matter_auto_summary(matter.id)

        # Incremental path: no full assembly; context carries the previous
        # summary and only the fresh record
        mock_ai.assemble.assert_not_called()
        system_context = mock_ai.call_args.kwargs["system_context"]
        assert "A fresh summary." in system_context
        assert "Deposition prep" in system_context
        assert "Old strategy memo" not in system_context

        conversation.refresh_from_db()
        assert Conversation.objects.filter(matter=matter).count() == 1
        assert conversation.created_at == original_created_at

        messages = list(conversation.messages.all())
        assert len(messages) == 2
        assert messages[0].content == AUTO_SUMMARY_UPDATE_PROMPT
        assert messages[1].content == "An even fresher summary."

    def test_incremental_run_with_no_new_records(self, matter, mock_ai):
        refresh_matter_auto_summary(matter.id)

        mock_ai.return_value = ("Same story, new day.", 500, 100)
        refresh_matter_auto_summary(matter.id)

        system_context = mock_ai.call_args.kwargs["system_context"]
        assert "No records have been added or changed" in system_context
        assert (
            Conversation.objects.get(matter=matter).messages.last().content
            == "Same story, new day."
        )

    def test_large_delta_falls_back_to_full_context(self, matter, mock_ai, monkeypatch):
        refresh_matter_auto_summary(matter.id)
        Note.objects.create(matter=matter, title="Big filing", content="x" * 100)

        monkeypatch.setattr("apps.case.ai.auto_summary.INCREMENTAL_FALLBACK_CHARS", 10)
        mock_ai.assemble.reset_mock()
        refresh_matter_auto_summary(matter.id)

        mock_ai.assemble.assert_called_once()
        assert mock_ai.call_args.kwargs["system_context"] == "FULL CONTEXT"
        messages = Conversation.objects.get(matter=matter).messages
        assert messages.first().content == AUTO_SUMMARY_PROMPT

    def test_gemini_failure_keeps_previous_summary(self, matter, mock_ai):
        refresh_matter_auto_summary(matter.id)

        mock_ai.side_effect = Exception("Gemini down")
        refresh_matter_auto_summary(matter.id)

        conversation = Conversation.objects.get(matter=matter)
        messages = list(conversation.messages.all())
        assert len(messages) == 2
        assert messages[1].content == "A fresh summary."

    def test_empty_response_keeps_previous_summary(self, matter, mock_ai):
        refresh_matter_auto_summary(matter.id)

        mock_ai.return_value = ("   ", 0, 0)
        refresh_matter_auto_summary(matter.id)

        messages = list(Conversation.objects.get(matter=matter).messages.all())
        assert len(messages) == 2
        assert messages[1].content == "A fresh summary."

    def test_stray_duplicates_consolidated(self, matter, mock_ai):
        first = Conversation.objects.create(
            matter=matter, title=AUTO_SUMMARY_TITLE, user=None
        )
        Conversation.objects.create(matter=matter, title=AUTO_SUMMARY_TITLE, user=None)

        refresh_matter_auto_summary(matter.id)

        conversations = Conversation.objects.filter(matter=matter)
        assert conversations.count() == 1
        assert conversations.first().id == first.id

    def test_human_conversation_with_same_title_untouched(self, matter, user, mock_ai):
        human = Conversation.objects.create(
            matter=matter, title=AUTO_SUMMARY_TITLE, user=user
        )
        Message.objects.create(
            conversation=human, role="user", content="my own chat", user=user
        )

        refresh_matter_auto_summary(matter.id)

        human.refresh_from_db()
        assert human.messages.count() == 1
        assert human.messages.first().content == "my own chat"
        assert (
            Conversation.objects.filter(matter=matter, title=AUTO_SUMMARY_TITLE).count()
            == 2
        )

    def test_missing_matter_does_not_crash(self, mock_ai):
        refresh_matter_auto_summary(999999)
        assert Conversation.objects.count() == 0
