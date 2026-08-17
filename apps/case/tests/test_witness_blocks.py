"""Tests for AI-created witnesses (create-witnesses fenced blocks)."""

import json

import pytest

from apps.case.ai.context import format_witnesses
from apps.case.ai.models import Conversation
from apps.case.ai.tasks import process_ai_request
from apps.case.ai.witness_blocks import apply_witness_blocks
from apps.case.models import Witness

pytestmark = pytest.mark.django_db


def block(entries):
    return "Done.\n\n```create-witnesses\n" + json.dumps(entries) + "\n```"


# ── Block parsing ────────────────────────────────────────────────────────────


def test_witness_block_creates_witness(user, matter):
    text = apply_witness_blocks(
        block(
            [
                {
                    "name": "Dr. Alice Reed",
                    "affiliation": "Treating physician",
                    "alignment": "Friendly",
                    "knowledge": "Treated the plaintiff after the fall",
                    "phone": "555-0100",
                    "email": "reed@clinic.example",
                    "address": "1 Clinic Way",
                    "importance": 9,
                }
            ]
        ),
        matter,
        user,
    )
    witness = Witness.objects.get()
    assert witness.matter_id == matter.id
    assert witness.user_id == user.id
    assert witness.name == "Dr. Alice Reed"
    assert witness.affiliation == "Treating physician"
    assert witness.alignment == "friendly"  # normalized to the stored value
    assert witness.knowledge == "Treated the plaintiff after the fall"
    assert witness.phone == "555-0100"
    assert witness.email == "reed@clinic.example"
    assert witness.address == "1 Clinic Way"
    assert witness.importance == 7  # clamped
    assert "Added witness: **Dr. Alice Reed** (Friendly)" in text
    assert "```create-witnesses" not in text


def test_optional_fields_default(user, matter):
    apply_witness_blocks(block([{"name": "Bob Smith"}]), matter, user)
    witness = Witness.objects.get()
    assert witness.affiliation == ""
    assert witness.alignment == "neutral"
    assert witness.knowledge == ""
    assert witness.phone == ""
    assert witness.email == ""
    assert witness.address == ""
    assert witness.importance == 4


def test_bad_optional_fields_degrade(user, matter):
    apply_witness_blocks(
        block(
            [
                {
                    "name": "Bob Smith",
                    "alignment": "adversarial",
                    "email": "unknown",
                    "importance": "high",
                }
            ]
        ),
        matter,
        user,
    )
    witness = Witness.objects.get()
    assert witness.alignment == "neutral"
    assert witness.email == ""
    assert witness.importance == 4


def test_missing_name_skipped(user, matter):
    text = apply_witness_blocks(
        block([{"affiliation": "Neighbor", "knowledge": "Saw the crash"}]),
        matter,
        user,
    )
    assert Witness.objects.count() == 0
    assert "(no witnesses created)" in text


def test_existing_witness_not_duplicated(user, matter):
    Witness.objects.create(matter=matter, name="Bob Smith", alignment="hostile")
    text = apply_witness_blocks(
        block([{"name": "bob smith", "alignment": "friendly"}]), matter, user
    )
    witness = Witness.objects.get()
    assert witness.alignment == "hostile"  # untouched
    assert "Already on the witness list: **Bob Smith**" in text


def test_invalid_json_left_alone(user, matter):
    text = "```create-witnesses\nnot json at all\n```"
    result = apply_witness_blocks(text, matter, user)
    assert result == text
    assert Witness.objects.count() == 0


# ── Context section ──────────────────────────────────────────────────────────


def test_format_witnesses_empty(matter):
    assert format_witnesses(matter) == "No witnesses recorded."


def test_format_witnesses_lists_fields(matter):
    Witness.objects.create(
        matter=matter,
        name="Dr. Alice Reed",
        affiliation="Treating physician",
        alignment="friendly",
        knowledge="Treated the plaintiff",
        importance=6,
    )
    text = format_witnesses(matter)
    assert "Dr. Alice Reed (Friendly, importance 6) - Treating physician" in text
    assert "Knows: Treated the plaintiff" in text


# ── Worker wiring ────────────────────────────────────────────────────────────


def test_classic_chat_applies_witness_blocks(user, matter, monkeypatch):
    """process_ai_request appends the protocol and applies the block."""
    from apps.case.ai.status import status_cache as cache

    conversation = Conversation.objects.create(
        matter=matter, user=user, llm="claude-opus", kind="classic"
    )
    conversation.messages.create(role="user", user=user, content="Add the witness")

    captured = {}

    def fake_send(context_text, chat_history, model, is_cancelled=None):
        captured["context"] = context_text
        return (
            block([{"name": "Bob Smith", "knowledge": "Saw the crash"}]),
            10,
            10,
        )

    monkeypatch.setattr("apps.case.ai.tasks.send_to_claude", fake_send)

    process_ai_request(
        conversation.id, matter.id, "Add the witness", user.id, "claude-opus"
    )

    assert "RECORDING WITNESSES" in captured["context"]
    assert "## Witnesses" in captured["context"]
    witness = Witness.objects.get()
    assert witness.name == "Bob Smith"
    assert witness.matter_id == matter.id

    status = cache.get(f"ai_status_{conversation.id}")
    assert status["status"] == "complete"
    assert "Added witness: **Bob Smith**" in status["response"]
    assert "```create-witnesses" not in status["response"]
