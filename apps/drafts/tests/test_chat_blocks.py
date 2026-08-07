"""Tests for the draft-edits block contract in case chat."""

import pytest
from django.utils import timezone

from apps.drafts import chat
from apps.drafts.models import CompanionRound
from apps.drive.redline import DeleteParagraph, InsertParagraphs, RedlineEdit

pytestmark = pytest.mark.django_db

BLOCK = '```draft-edits\n[{"old": "Some text.", "new": "Better text."}]\n```'


def _connect(link):
    link.companion_seen = timezone.now()
    link.save()


def _answer_on_sleep(monkeypatch, link, **round_fields):
    """Make the worker's wait loop see an answered round on its first tick.

    A real companion answers from another process; in tests that would need
    a second DB connection, which cannot see this test's transaction. Hooking
    the wait loop's sleep updates the round on the same connection instead.
    """

    def fake_sleep(seconds):
        round_ = CompanionRound.objects.get(link=link)
        for field, value in round_fields.items():
            setattr(round_, field, value)
        round_.save()

    monkeypatch.setattr(chat.time, "sleep", fake_sleep)


def test_block_routes_to_connected_companion(link, monkeypatch):
    _connect(link)
    _answer_on_sleep(
        monkeypatch,
        link,
        status="applied",
        result=[{"op": "replace", "replacements": 1}],
    )
    result = chat.apply_edit_blocks(f"Done.\n\n{BLOCK}", link)
    assert "in the open LibreOffice document" in result
    assert "```draft-edits" not in result


def test_block_refused_without_companion(link):
    result = chat.apply_edit_blocks(f"Done.\n\n{BLOCK}", link)
    assert "not connected" in result
    assert "Connect to drafting session" in result
    assert CompanionRound.objects.count() == 0


def test_companion_failure_reported(link, monkeypatch):
    _connect(link)
    _answer_on_sleep(
        monkeypatch, link, status="failed", error="text not found", edit_index=0
    )
    result = chat.apply_edit_blocks(f"Done.\n\n{BLOCK}", link)
    assert "were not applied" in result
    assert "edit 1: text not found" in result


def test_companion_timeout_expires_round(link, monkeypatch):
    _connect(link)
    monkeypatch.setattr(chat, "COMPANION_WAIT_SECONDS", 1)
    result = chat.apply_edit_blocks(f"Done.\n\n{BLOCK}", link)
    assert "did not respond in time" in result
    assert CompanionRound.objects.get(link=link).status == "expired"


def test_malformed_block_left_in_place(link):
    text = "```draft-edits\nnot json\n```"
    assert chat.apply_edit_blocks(text, link) == text
    text = '```draft-edits\n["just strings"]\n```'
    assert chat.apply_edit_blocks(text, link) == text


def test_unknown_op_leaves_block_in_place(link):
    text = '```draft-edits\n[{"op": "reorder_sections", "text": "x"}]\n```'
    assert chat.apply_edit_blocks(text, link) == text
    assert CompanionRound.objects.count() == 0


def test_text_without_block_untouched(link):
    text = "Just a normal reply about the draft."
    assert chat.apply_edit_blocks(text, link) == text


def test_ops_parse_into_round_wire_form(link, monkeypatch):
    """The queued round carries the wire-form dicts, occurrence included."""
    _connect(link)
    _answer_on_sleep(monkeypatch, link, status="applied")
    block = """```draft-edits
[{"old": "a", "new": "b", "occurrence": 3},
 {"op": "delete_paragraph", "text": "boilerplate", "occurrence": 2},
 {"op": "insert_after", "anchor": "x", "paragraphs": ["New."]}]
```"""
    chat.apply_edit_blocks(block, link)
    round_ = CompanionRound.objects.get(link=link)
    assert round_.edits == [
        {
            "op": "replace",
            "old": "a",
            "new": "b",
            "replace_all": False,
            "occurrence": 3,
        },
        {"op": "delete_paragraph", "text": "boilerplate", "occurrence": 2},
        {"op": "insert_after", "anchor": "x", "paragraphs": ["New."]},
    ]


def test_parse_edit_block_objects():
    edits = chat._parse_edit_block(
        '[{"old": "a", "new": "b"},'
        ' {"op": "delete_paragraph", "text": "t"},'
        ' {"op": "insert_after", "anchor": "x", "paragraphs": ["p1", "p2"]}]'
    )
    assert edits == [
        RedlineEdit(old="a", new="b", replace_all=False),
        DeleteParagraph(text="t"),
        InsertParagraphs(anchor="x", paragraphs=["p1", "p2"]),
    ]


def test_draft_section_contains_protocol_and_text(link, monkeypatch):
    monkeypatch.setattr("apps.drafts.services.refresh_if_stale", lambda link_: None)
    section = chat.build_draft_section(link)
    assert "PROPOSING EDITS" in section
    assert 'THE DRAFT: "motion.odt"' in section
    assert "# MOTION" in section
    assert "occurrence" in section
