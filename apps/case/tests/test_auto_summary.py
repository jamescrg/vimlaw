from unittest.mock import patch

import pytest

from apps.case.ai.auto_summary import (
    AUTO_AGENDA_PROMPT,
    AUTO_AGENDA_TITLE,
    AUTO_SUMMARY_PROMPT,
    AUTO_SUMMARY_TITLE,
    AUTO_SUMMARY_UPDATE_PROMPT,
    refresh_auto_summaries,
    refresh_matter_auto_agenda,
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
        patch("django_q.tasks.async_task") as async_task,
    ):
        send.assemble = assemble
        send.async_task = async_task
        yield send


def summary_conv(matter):
    return Conversation.objects.get(
        matter=matter, title=AUTO_SUMMARY_TITLE, user__isnull=True
    )


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
            False,
            task_name=f"AutoSummary-{matter.id}",
            group="auto_summary",
        )
        queued_ids = {call.args[1] for call in async_task.call_args_list}
        assert closed.id not in queued_ids
        assert pending.id not in queued_ids


class TestScheduledGuard:
    def test_scheduled_run_skipped_off_prod(self, matter, mock_ai, settings):
        from apps.case.ai.auto_summary import scheduled_refresh_auto_summaries

        settings.ENV = "dev"
        assert scheduled_refresh_auto_summaries() == 0
        mock_ai.async_task.assert_not_called()

    def test_scheduled_run_dispatches_on_prod(self, matter, mock_ai, settings):
        from apps.case.ai.auto_summary import (
            scheduled_refresh_auto_summaries,
            scheduled_refresh_auto_summaries_full,
        )

        settings.ENV = "prod"
        assert scheduled_refresh_auto_summaries() == 1
        assert scheduled_refresh_auto_summaries_full() == 1
        assert mock_ai.async_task.call_args.args[2] is True


class TestWorker:
    def test_first_run_creates_conversation(self, matter, mock_ai):
        refresh_matter_auto_summary(matter.id)

        conversation = summary_conv(matter)
        assert conversation.title == AUTO_SUMMARY_TITLE
        assert conversation.llm == "gemini-pro-latest"
        assert conversation.ai_context == "always"
        assert conversation.vet_citations is False
        assert conversation.user is None
        assert conversation.summary == "A fresh summary."

        mock_ai.assemble.assert_called_once()
        assert mock_ai.call_args.kwargs["system_context"] == "FULL CONTEXT"
        assert mock_ai.call_args.kwargs["model"] == "gemini-pro-latest"

        messages = list(conversation.messages.all())
        assert [m.role for m in messages] == ["user", "assistant"]
        assert messages[0].content == AUTO_SUMMARY_PROMPT
        assert messages[1].content == "A fresh summary."
        assert messages[1].input_tokens == 1000
        assert messages[1].output_tokens == 200

    def test_summary_worker_queues_agenda(self, matter, mock_ai):
        refresh_matter_auto_summary(matter.id)

        mock_ai.async_task.assert_called_once_with(
            "apps.case.ai.auto_summary.refresh_matter_auto_agenda",
            matter.id,
            False,
            task_name=f"AutoAgenda-{matter.id}",
            group="auto_summary",
        )

    def test_agenda_worker_creates_agenda_thread(self, matter, mock_ai):
        mock_ai.return_value = ("The plan.", 2000, 400)
        refresh_matter_auto_agenda(matter.id)

        conversation = Conversation.objects.get(
            matter=matter, title=AUTO_AGENDA_TITLE, user__isnull=True
        )
        assert conversation.llm == "gemini-pro-latest"
        assert conversation.ai_context == "always"
        messages = list(conversation.messages.all())
        assert [m.role for m in messages] == ["user", "assistant"]
        assert messages[0].content == AUTO_AGENDA_PROMPT
        assert messages[1].content == "The plan."
        # Agenda does not queue anything further
        mock_ai.async_task.assert_not_called()

    def test_second_run_is_incremental_and_replaces_messages(self, matter, mock_ai):
        refresh_matter_auto_summary(matter.id)
        conversation = summary_conv(matter)
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
        assert (
            Conversation.objects.filter(matter=matter, title=AUTO_SUMMARY_TITLE).count()
            == 1
        )
        assert conversation.created_at == original_created_at

        messages = list(conversation.messages.all())
        assert len(messages) == 2
        assert messages[0].content == AUTO_SUMMARY_UPDATE_PROMPT
        assert messages[1].content == "An even fresher summary."

    def test_thread_discussion_feeds_next_run_then_resets(self, matter, user, mock_ai):
        refresh_matter_auto_summary(matter.id)
        conversation = summary_conv(matter)
        Message.objects.create(
            conversation=conversation,
            role="user",
            content="Focus on the boundary dispute, drop the billing angle.",
            user=user,
        )
        Message.objects.create(
            conversation=conversation,
            role="assistant",
            content="Understood, I will emphasize the boundary dispute.",
        )

        mock_ai.return_value = ("A guided summary.", 900, 180)
        refresh_matter_auto_summary(matter.id)

        system_context = mock_ai.call_args.kwargs["system_context"]
        # Baseline is the original nightly reply, not the discussion reply
        assert "A fresh summary." in system_context
        assert "Attorney Feedback on the Previous Version" in system_context
        assert "Focus on the boundary dispute" in system_context
        assert "I will emphasize the boundary dispute" in system_context

        # Thread resets to the canonical pair; feedback was consumed
        messages = list(conversation.messages.all())
        assert len(messages) == 2
        assert messages[1].content == "A guided summary."

    def test_incremental_run_with_no_new_records(self, matter, mock_ai):
        refresh_matter_auto_summary(matter.id)

        mock_ai.return_value = ("Same story, new day.", 500, 100)
        refresh_matter_auto_summary(matter.id)

        system_context = mock_ai.call_args.kwargs["system_context"]
        assert "No records have been added or changed" in system_context
        assert "Attorney Feedback" not in system_context
        assert summary_conv(matter).messages.last().content == "Same story, new day."

    def test_large_delta_falls_back_to_full_context(self, matter, mock_ai, monkeypatch):
        refresh_matter_auto_summary(matter.id)
        Note.objects.create(matter=matter, title="Big filing", content="x" * 100)

        monkeypatch.setattr("apps.case.ai.auto_summary.INCREMENTAL_FALLBACK_CHARS", 10)
        mock_ai.assemble.reset_mock()
        refresh_matter_auto_summary(matter.id)

        mock_ai.assemble.assert_called_once()
        assert mock_ai.call_args.kwargs["system_context"] == "FULL CONTEXT"
        assert summary_conv(matter).messages.first().content == AUTO_SUMMARY_PROMPT

    def test_force_full_rebuilds_but_keeps_feedback(self, matter, user, mock_ai):
        refresh_matter_auto_summary(matter.id)
        conversation = summary_conv(matter)
        Message.objects.create(
            conversation=conversation, role="user", content="my guidance", user=user
        )

        mock_ai.assemble.reset_mock()
        refresh_matter_auto_summary(matter.id, force_full=True)

        mock_ai.assemble.assert_called_once()
        system_context = mock_ai.call_args.kwargs["system_context"]
        assert system_context.startswith("FULL CONTEXT")
        assert "my guidance" in system_context
        assert mock_ai.async_task.call_args.args[2] is True
        assert conversation.messages.count() == 2
        assert conversation.messages.first().content == AUTO_SUMMARY_PROMPT

    def test_prompt_change_forces_full_rebuild(self, matter, mock_ai):
        refresh_matter_auto_summary(matter.id)
        conversation = summary_conv(matter)
        conversation.messages.filter(role="user").update(
            content="An old, since-retired prompt."
        )

        mock_ai.assemble.reset_mock()
        refresh_matter_auto_summary(matter.id)

        mock_ai.assemble.assert_called_once()
        assert mock_ai.call_args.kwargs["system_context"] == "FULL CONTEXT"
        assert conversation.messages.first().content == AUTO_SUMMARY_PROMPT

    def test_gemini_failure_keeps_previous_thread_and_feedback(
        self, matter, user, mock_ai
    ):
        refresh_matter_auto_summary(matter.id)
        conversation = summary_conv(matter)
        Message.objects.create(
            conversation=conversation, role="user", content="my guidance", user=user
        )

        mock_ai.side_effect = Exception("Gemini down")
        refresh_matter_auto_summary(matter.id)

        messages = list(conversation.messages.all())
        assert len(messages) == 3
        assert messages[1].content == "A fresh summary."
        assert messages[2].content == "my guidance"

    def test_empty_response_keeps_previous_summary(self, matter, mock_ai):
        refresh_matter_auto_summary(matter.id)

        mock_ai.return_value = ("   ", 0, 0)
        refresh_matter_auto_summary(matter.id)

        messages = list(summary_conv(matter).messages.all())
        assert len(messages) == 2
        assert messages[1].content == "A fresh summary."

    def test_stray_duplicates_consolidated(self, matter, mock_ai):
        first = Conversation.objects.create(
            matter=matter, title=AUTO_SUMMARY_TITLE, user=None
        )
        Conversation.objects.create(matter=matter, title=AUTO_SUMMARY_TITLE, user=None)

        refresh_matter_auto_summary(matter.id)

        conversations = Conversation.objects.filter(
            matter=matter, title=AUTO_SUMMARY_TITLE
        )
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
        refresh_matter_auto_agenda(999999)
        assert Conversation.objects.count() == 0
