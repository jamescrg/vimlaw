"""The working set: reads scanned from agent_run, re-fetched and carried."""

import pytest
from django.core.cache import cache as django_cache

from apps.case.ai import agent_working_set
from apps.case.ai.agent_prompt import build_agent_history, build_agent_system
from apps.case.ai.agent_working_set import build_working_set, reads_from_steps
from apps.case.ai.models import Conversation, Message
from apps.case.models import CaseLaw

pytestmark = pytest.mark.django_db


@pytest.fixture
def conversation(matter, user):
    return Conversation.objects.create(
        matter=matter, user=user, kind="agent", title="T"
    )


def add_turn(conversation, user, steps, question="Q"):
    Message.objects.create(
        conversation=conversation, role="user", content=question, user=user
    )
    Message.objects.create(
        conversation=conversation,
        role="assistant",
        content="Answer",
        agent_run={"steps": steps},
    )


def read_step(kind, ident, name):
    return {"type": "tool", "kind": kind, "id": ident, "name": name}


@pytest.fixture
def text_document(document):
    document.ocr_text = "Alpha " * 50 + "spoliation letter " + "omega " * 50
    document.ocr_status = "completed"
    document.save(update_fields=["ocr_text", "ocr_status"])
    return document


class TestReadsFromSteps:
    def test_dedupe_order_and_recency(self, conversation, user):
        add_turn(
            conversation,
            user,
            [
                read_step("document", 1, "Complaint"),
                read_step("email", "t1", "Re: dates"),
                {"type": "tool", "kind": "note", "id": 3, "name": "Bad", "error": "x"},
                {"type": "tool", "kind": "search", "id": None, "name": "q"},
                {"type": "turn", "n": 1},
            ],
        )
        add_turn(conversation, user, [read_step("document", 1, "Complaint")])
        reads = reads_from_steps(conversation)
        assert set(reads) == {("document", "1"), ("email", "t1")}
        doc = reads[("document", "1")]
        assert doc["first"] == 0
        assert doc["last"] > reads[("email", "t1")]["last"]

    def test_empty_without_conversation(self):
        assert reads_from_steps(None) == {}


class TestBuildWorkingSet:
    def test_document_carried_verbatim(self, conversation, matter, user, text_document):
        add_turn(
            conversation,
            user,
            [read_step("document", text_document.id, text_document.name)],
        )
        working = build_working_set(conversation, matter)
        assert "## Materials in View" in working.text
        assert f"[doc:{text_document.id}]" in working.text
        assert text_document.ocr_text in working.text
        assert working.carried == {("document", str(text_document.id))}
        assert working.evicted == 0

    def test_item_truncation(
        self, conversation, matter, user, text_document, monkeypatch
    ):
        monkeypatch.setattr(agent_working_set, "WORKING_SET_ITEM_CHARS", 50)
        add_turn(
            conversation,
            user,
            [read_step("document", text_document.id, text_document.name)],
        )
        working = build_working_set(conversation, matter)
        assert text_document.ocr_text not in working.text
        assert "characters carried; use the matching read tool" in working.text
        assert working.carried == {("document", str(text_document.id))}

    def test_lru_eviction_keeps_most_recent(
        self, conversation, matter, user, text_document
    ):
        from apps.case.models import Document

        other = Document.objects.create(
            matter=matter, name="Answer brief", category="Evidence", created_by=user
        )
        other.ocr_text = "Beta " * 200
        other.ocr_status = "completed"
        other.save(update_fields=["ocr_text", "ocr_status"])
        add_turn(
            conversation,
            user,
            [read_step("document", text_document.id, text_document.name)],
        )
        add_turn(conversation, user, [read_step("document", other.id, other.name)])
        cap = len(agent_working_set.HEADER) + len(other.ocr_text) + 200
        working = build_working_set(conversation, matter, max_chars=cap)
        assert working.carried == {("document", str(other.id))}
        assert working.evicted == 1

    def test_never_and_deleted_not_carried_not_evicted(
        self, conversation, matter, user, text_document
    ):
        add_turn(
            conversation,
            user,
            [
                read_step("document", text_document.id, text_document.name),
                read_step("document", 999_999, "Gone"),
            ],
        )
        text_document.ai_context = "never"
        text_document.save(update_fields=["ai_context"])
        working = build_working_set(conversation, matter)
        assert working.text == "" and working.carried == set()
        assert working.evicted == 0

    def test_caselaw_opinion_only_from_cache(self, conversation, matter, user):
        case = CaseLaw.objects.create(
            matter=matter,
            citation="1 Ga. 1",
            case_name="Smith v. Jones",
            notes="Key holding on fees.",
            summary="Fees follow the contract.",
        )
        add_turn(conversation, user, [read_step("caselaw", case.id, case.case_name)])
        working = build_working_set(conversation, matter)
        assert "Smith v. Jones" in working.text
        assert "Key holding on fees." in working.text
        assert "Opinion text not carried" in working.text

        django_cache.set(f"agent_opinion_{case.id}", "THE OPINION TEXT", 60)
        working = build_working_set(conversation, matter)
        assert "Opinion:\nTHE OPINION TEXT" in working.text

    def test_note_email_and_conversation_fetch(self, conversation, matter, user):
        from django.utils import timezone

        from apps.mail.models import Email
        from apps.notes.models import Note

        note = Note.objects.create(matter=matter, title="Memo", content="Matter memo")
        Email.objects.create(
            matter=matter,
            gmail_id="m1",
            thread_id="t1",
            sender="oc@example.com",
            recipients="james@example.com",
            subject="Depo dates",
            body_text="Tuesday works.",
            date=timezone.now(),
        )
        earlier = Conversation.objects.create(matter=matter, user=user, title="Earlier")
        Message.objects.create(
            conversation=earlier, role="assistant", content="Earlier answer"
        )
        add_turn(
            conversation,
            user,
            [
                read_step("note", note.id, note.title),
                read_step("email", "t1", "Depo dates"),
                read_step("conversation", earlier.id, "Earlier"),
            ],
        )
        working = build_working_set(conversation, matter)
        assert "Matter memo" in working.text
        assert "Tuesday works." in working.text
        assert "Earlier answer" in working.text
        assert len(working.carried) == 3


class TestSystemIntegration:
    def test_carried_reads_leave_the_note(
        self, conversation, matter, user, text_document
    ):
        add_turn(
            conversation,
            user,
            [
                read_step("document", text_document.id, text_document.name),
                read_step("document", 999_999, "Gone"),
            ],
            question="What does the letter say?",
        )
        Message.objects.create(
            conversation=conversation, role="user", content="Follow-up", user=user
        )
        logs = []
        segments, carried = build_agent_system(
            matter, user, conversation, "Follow-up", log=logs.append
        )
        assert len(segments) == 3
        assert text_document.ocr_text in segments[1]
        assert carried == {("document", str(text_document.id))}
        assert any(log.startswith("Carrying 1 material in view") for log in logs)

        history = build_agent_history(conversation, exclude_reads=carried)
        note = history[-1]["content"]
        assert "Gone (doc:999999)" in note
        assert text_document.name not in note


class TestOpinionCarry:
    def test_opinion_carried_from_cache_only(self, conversation, matter, user):
        django_cache.set(
            "agent_opinion_cluster_777",
            {
                "cluster_id": 777,
                "case_name": "Dollar Concrete v. Watson",
                "citation": "207 Ga. App. 452 (1993)",
                "date_filed": "1993-02-01",
                "url": "",
                "text": "The joinder rule text.",
            },
            60,
        )
        add_turn(
            conversation,
            user,
            [
                read_step("opinion", 777, "Dollar Concrete v. Watson"),
                read_step("opinion", 778, "Uncached v. Case"),
            ],
        )
        working = build_working_set(conversation, matter)
        assert (
            "### Opinion [cluster:777]: Dollar Concrete v. Watson, "
            "207 Ga. App. 452 (1993)" in working.text
        )
        assert "The joinder rule text." in working.text
        assert working.carried == {("opinion", "777")}
