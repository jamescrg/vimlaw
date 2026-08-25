"""Agent orientation: the material index, the system segments, the history note."""

import pytest
from django.utils import timezone

from apps.case.ai import agent_prompt
from apps.case.ai.agent_prompt import (
    build_agent_history,
    build_agent_system,
    earlier_reads_note,
    format_material_index,
)
from apps.case.ai.models import Conversation, Message
from apps.case.ai.selector import ManifestItem, build_manifest

pytestmark = pytest.mark.django_db


@pytest.fixture
def pinned_document(document):
    document.ocr_text = "Complaint text " * 100
    document.ocr_status = "completed"
    document.ai_context = "always"
    document.save(update_fields=["ocr_text", "ocr_status", "ai_context"])
    return document


class TestManifestIncludeAlways:
    def test_default_lists_only_auto(self, matter, pinned_document):
        items, _ = build_manifest(matter)
        assert [i.item_id for i in items if i.item_type == "document"] == []

    def test_include_always_lists_pinned_with_handle(self, matter, pinned_document):
        items, _ = build_manifest(matter, include_always=True)
        (doc,) = [i for i in items if i.item_type == "document"]
        assert doc.pinned is True
        assert doc.handle == f"doc:{pinned_document.id}"
        assert doc.size_chars == len(pinned_document.ocr_text)

    def test_never_stays_hidden(self, matter, pinned_document):
        pinned_document.ai_context = "never"
        pinned_document.save(update_fields=["ai_context"])
        items, _ = build_manifest(matter, include_always=True)
        assert not [i for i in items if i.item_type == "document"]


def item(kind, ident, **kw):
    base = dict(
        item_type=kind,
        item_id=ident,
        name=f"{kind} {ident}",
        category="pleading",
        date="2025-03-02",
        description="A description of the item. " * 20,
        word_count=100,
        importance=4,
        handle=f"{kind}:{ident}",
        size_chars=41_000,
    )
    base.update(kw)
    return ManifestItem(**base)


class TestIndex:
    def test_line_format(self):
        text = format_material_index(
            [item("document", 12, name="Complaint", pinned=True, description="Short.")]
        )
        assert "### Documents" in text
        assert (
            "- [document:12] Complaint | pleading | 2025-03-02 | 41k chars | "
            "importance 4 | pinned\n  Short." in text
        )

    def test_importance_then_date_order(self):
        text = format_material_index(
            [
                item("document", 1, name="Old low", importance=2, date="2024-01-01"),
                item("document", 2, name="New high", importance=6, date="2025-01-01"),
                item("document", 3, name="Old high", importance=6, date="2023-01-01"),
            ]
        )
        assert text.index("New high") < text.index("Old high") < text.index("Old low")

    def test_cap_keeps_document_descriptions_longest_then_collapses(self):
        items = [item("conversation", i) for i in range(30)] + [item("document", 1)]
        full = format_material_index(items)
        assert "A description of the item." in full
        trimmed = format_material_index(items, max_chars=len(full) - 1)
        docs_part, convs_part = trimmed.split("### Earlier AI conversations")
        assert "A description of the item." in docs_part
        assert "A description of the item." not in convs_part
        assert "[conversation:3]" in convs_part
        bare = format_material_index(items, max_chars=len(trimmed) - 1)
        assert "A description of the item." not in bare
        assert "[conversation:3]" in bare
        collapsed = format_material_index(items, max_chars=600)
        assert "30 items, not listed" in collapsed
        assert "[document:1]" in collapsed

    def test_empty(self):
        assert "No materials" in format_material_index([])


class TestSystem:
    def test_segments(self, matter, user, pinned_document):
        logs = []
        (segment_a, working_set, segment_b), carried = build_agent_system(
            matter, user, None, "What happened?", log=logs.append
        )
        assert working_set == "" and carried == set()
        assert "## Working Method" in segment_a
        assert "at most 40 tool calls and 600,000 characters" in segment_a
        assert "## Legal Research Method" in segment_a
        assert "CITING SOURCES" in segment_a
        assert "## Current Matter: Test Matter" in segment_a
        assert f"[doc:{pinned_document.id}] Test Document" in segment_a
        assert "pinned" in segment_a
        assert "## Highlights" in segment_a and "## Timeline" in segment_a
        assert "Today is" in segment_b and "## Requesting Party" in segment_b
        assert "Working Method" not in segment_b
        assert logs and logs[-1].startswith("Oriented on the case file: 1 materials")
        assert "1 pinned" in logs[-1]

    def test_armed_protocol_lands_in_tail(self, matter, user):
        conversation = Conversation.objects.create(
            matter=matter, user=user, kind="agent", title="T"
        )
        logs = []
        (segment_a, _, segment_b), _ = build_agent_system(
            matter,
            user,
            conversation,
            "Add these facts to the timeline",
            log=logs.append,
        )
        assert "create-facts" in segment_b
        assert "create-facts" not in segment_a
        assert "Write protocols included: facts" in logs

    def test_large_sections_become_pointers(self, matter, user, monkeypatch):
        monkeypatch.setattr(agent_prompt, "INLINE_SECTIONS_MAX_CHARS", 5)
        (segment_a, _, _), _ = build_agent_system(matter, user, None, "q")
        assert "Too large to include here" in segment_a
        assert "## Timeline" not in segment_a


class TestHistory:
    def test_earlier_reads_note(self, matter, user):
        conversation = Conversation.objects.create(
            matter=matter, user=user, kind="agent", title="T"
        )
        Message.objects.create(
            conversation=conversation, role="user", content="First", user=user
        )
        Message.objects.create(
            conversation=conversation,
            role="assistant",
            content="Answer",
            agent_run={
                "steps": [
                    {"type": "tool", "kind": "document", "id": 12, "name": "Complaint"},
                    {"type": "tool", "kind": "email", "id": "t1", "name": "Re: dates"},
                    {"type": "tool", "kind": "document", "id": 12, "name": "Complaint"},
                    {
                        "type": "tool",
                        "kind": "note",
                        "id": 3,
                        "name": "Bad",
                        "error": "x",
                    },
                    {"type": "turn", "n": 1},
                ]
            },
        )
        Message.objects.create(
            conversation=conversation,
            role="user",
            content="Second",
            user=user,
            created_at=timezone.now(),
        )
        note = earlier_reads_note(conversation)
        assert "Complaint (doc:12)" in note
        assert "Re: dates (thread:t1)" in note
        assert "Bad" not in note
        assert note.count("Complaint") == 1

        history = build_agent_history(conversation)
        assert history[-1]["role"] == "user"
        assert history[-1]["content"].endswith(note)
        assert "Second" in history[-1]["content"]
        assert note not in history[0]["content"]

    def test_no_note_without_reads(self, matter, user):
        conversation = Conversation.objects.create(
            matter=matter, user=user, kind="agent", title="T"
        )
        Message.objects.create(
            conversation=conversation, role="user", content="Only", user=user
        )
        assert earlier_reads_note(conversation) == ""
        assert build_agent_history(conversation)[-1]["content"].endswith("Only")
