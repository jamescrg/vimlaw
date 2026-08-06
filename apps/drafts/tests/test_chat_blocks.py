"""The draft-edits fenced-block contract (no LibreOffice needed)."""

import pytest

from apps.drafts import chat, services
from apps.drive.redline import (
    DeleteParagraph,
    InsertParagraphs,
    RedlineEdit,
    RedlineError,
)

pytestmark = pytest.mark.django_db

BLOCK = """Tightening the claim language as you asked.

```draft-edits
[{"old": "state a claim", "new": "state any claim"},
 {"old": "will be deleted", "new": "", "replace_all": true}]
```
"""


def test_valid_block_applies_and_confirms(session, monkeypatch):
    calls = {}

    def fake_apply(sess, edits):
        calls["edits"] = edits
        version = sess.versions.get(seq=0)
        version.seq = 1
        return version

    monkeypatch.setattr(services, "apply_edit_round", fake_apply)
    result = chat.apply_edit_blocks(BLOCK, session)

    assert calls["edits"] == [
        RedlineEdit(old="state a claim", new="state any claim", replace_all=False),
        RedlineEdit(old="will be deleted", new="", replace_all=True),
    ]
    assert "Applied 2 edits as tracked changes (version 1)." in result
    assert "```draft-edits" not in result
    assert "Tightening the claim language" in result


def test_failed_apply_reports_and_keeps_draft(session, monkeypatch):
    def fake_apply(sess, edits):
        raise RedlineError("text not found in draft: 'nope'", 0)

    monkeypatch.setattr(services, "apply_edit_round", fake_apply)
    result = chat.apply_edit_blocks(BLOCK, session)

    assert "were not applied" in result
    assert "edit 1: text not found" in result
    assert "The draft is unchanged." in result


def test_malformed_block_left_in_place(session, monkeypatch):
    def boom(sess, edits):  # pragma: no cover - must not be reached
        raise AssertionError("apply_edit_round called for malformed block")

    monkeypatch.setattr(services, "apply_edit_round", boom)
    text = "```draft-edits\nnot json\n```"
    assert chat.apply_edit_blocks(text, session) == text
    # A list of non-objects is also malformed.
    text = '```draft-edits\n["just strings"]\n```'
    assert chat.apply_edit_blocks(text, session) == text


def test_structural_ops_parse(session, monkeypatch):
    block = """```draft-edits
[{"op": "delete_paragraph", "text": "COUNT FOUR"},
 {"op": "delete_paragraph", "text": "entitled to recover attorney fees"},
 {"op": "insert_after", "anchor": "incorporates paragraphs 1 through 40", "paragraphs": ["87. New paragraph.", "88. Another."]},
 {"old": "liquidated damages", "new": "a penalty"}]
```"""
    seen = {}

    def fake_apply(sess, edits):
        seen["edits"] = edits
        return sess.versions.get(seq=0)

    monkeypatch.setattr(services, "apply_edit_round", fake_apply)
    result = chat.apply_edit_blocks(block, session)

    assert seen["edits"] == [
        DeleteParagraph(text="COUNT FOUR"),
        DeleteParagraph(text="entitled to recover attorney fees"),
        InsertParagraphs(
            anchor="incorporates paragraphs 1 through 40",
            paragraphs=["87. New paragraph.", "88. Another."],
        ),
        RedlineEdit(old="liquidated damages", new="a penalty", replace_all=False),
    ]
    assert "Applied 4 edits as tracked changes" in result


def test_occurrence_parses_on_every_op(session, monkeypatch):
    block = """```draft-edits
[{"old": "restates and incorporates", "new": "incorporates", "occurrence": 3},
 {"op": "delete_paragraph", "text": "boilerplate", "occurrence": 2},
 {"op": "insert_after", "anchor": "boilerplate", "paragraphs": ["New."], "occurrence": 1}]
```"""
    seen = {}

    def fake_apply(sess, edits):
        seen["edits"] = edits
        return sess.versions.get(seq=0)

    monkeypatch.setattr(services, "apply_edit_round", fake_apply)
    chat.apply_edit_blocks(block, session)

    assert seen["edits"] == [
        RedlineEdit(old="restates and incorporates", new="incorporates", occurrence=3),
        DeleteParagraph(text="boilerplate", occurrence=2),
        InsertParagraphs(anchor="boilerplate", paragraphs=["New."], occurrence=1),
    ]


def test_unknown_op_leaves_block_in_place(session, monkeypatch):
    def boom(sess, edits):  # pragma: no cover - must not be reached
        raise AssertionError("apply_edit_round called for unknown op")

    monkeypatch.setattr(services, "apply_edit_round", boom)
    text = '```draft-edits\n[{"op": "reorder_sections", "text": "x"}]\n```'
    assert chat.apply_edit_blocks(text, session) == text


def test_settled_session_refuses_edits(session):
    session.status = "published"
    session.save()
    result = chat.apply_edit_blocks(BLOCK, session)
    assert "were not applied" in result
    assert "no longer accepting edits" in result


def test_text_without_block_untouched(session):
    text = "Just a discussion of the draft, no edits."
    assert chat.apply_edit_blocks(text, session) == text
