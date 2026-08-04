"""The draft-edits fenced-block contract (no LibreOffice needed)."""

import pytest

from apps.drafts import chat, services
from apps.drive.redline import RedlineEdit, RedlineError

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


def test_settled_session_refuses_edits(session):
    session.status = "published"
    session.save()
    result = chat.apply_edit_blocks(BLOCK, session)
    assert "were not applied" in result
    assert "no longer accepting edits" in result


def test_text_without_block_untouched(session):
    text = "Just a discussion of the draft, no edits."
    assert chat.apply_edit_blocks(text, session) == text
