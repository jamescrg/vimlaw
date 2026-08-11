"""Tests for AI note writes (create-note / edit-note fenced blocks)."""

import json

import pytest

from apps.case.ai.note_blocks import apply_note_blocks
from apps.notes.models import Note, NoteFolder

pytestmark = pytest.mark.django_db


def create_block(entry):
    return "Done.\n\n```create-note\n" + json.dumps(entry) + "\n```"


def edit_block(entry):
    return "Done.\n\n```edit-note\n" + json.dumps(entry) + "\n```"


# ── Creation ─────────────────────────────────────────────────────────────────


def test_create_block_creates_matter_note(user, matter):
    text = apply_note_blocks(
        create_block(
            {
                "title": "Conclusion on service of process",
                "category": "analysis",
                "topic": "Service",
                "content": "## Conclusion\n\nService was defective.",
            }
        ),
        matter,
        user,
    )
    note = Note.objects.get()
    assert note.matter_id == matter.id
    assert note.author_id == user.id
    assert note.category == "analysis"
    assert note.topic == "Service"
    assert note.content.startswith("## Conclusion")
    assert "Created note: **Conclusion on service of process**" in text
    assert "```create-note" not in text


def test_create_bad_category_defaults(user, matter):
    apply_note_blocks(
        create_block({"title": "A valid title", "category": "sonnet", "content": "x"}),
        matter,
        user,
    )
    assert Note.objects.get().category == "note"


def test_create_requires_title_and_content(user, matter):
    text = apply_note_blocks(
        create_block({"title": "ok title", "content": ""}), matter, user
    )
    assert Note.objects.count() == 0
    assert "```create-note" in text  # left in place


def test_malformed_create_left_in_place(user, matter):
    raw = "Done.\n\n```create-note\nnot json\n```"
    assert apply_note_blocks(raw, matter, user) == raw
    assert Note.objects.count() == 0


# ── Editing ──────────────────────────────────────────────────────────────────


def test_edit_appends_to_matter_note(user, matter):
    note = Note.objects.create(matter=matter, title="Research", content="Existing.")
    text = apply_note_blocks(
        edit_block({"id": note.id, "mode": "append", "content": "New conclusion."}),
        matter,
        user,
    )
    note.refresh_from_db()
    assert note.content == "Existing.\n\nNew conclusion."
    assert "Appended to note: **Research**" in text


def test_edit_replace_rewrites(user, matter):
    note = Note.objects.create(matter=matter, title="Research", content="Old.")
    apply_note_blocks(
        edit_block({"id": note.id, "mode": "replace", "content": "New."}), matter, user
    )
    note.refresh_from_db()
    assert note.content == "New."


def test_edit_reaches_library_note(user, matter):
    folder = NoteFolder.objects.create(name="Library", ai_library=True)
    note = Note.objects.create(folder=folder, title="Service guide", content="Old.")
    text = apply_note_blocks(
        edit_block({"id": note.id, "content": "Addendum."}), matter, user
    )
    note.refresh_from_db()
    assert note.content.endswith("Addendum.")
    assert "Appended to library note: **Service guide**" in text


def test_edit_rejects_other_matter_note(user, matter, contact, practice_area):
    from apps.case.models import Matter

    other = Matter.objects.create(
        name="Other matter", client=contact, practice_area=practice_area
    )
    note = Note.objects.create(matter=other, title="Foreign", content="Old.")
    text = apply_note_blocks(edit_block({"id": note.id, "content": "x"}), matter, user)
    note.refresh_from_db()
    assert note.content == "Old."
    assert "not found or not editable" in text


def test_edit_rejects_non_library_standalone_note(user, matter):
    folder = NoteFolder.objects.create(name="Private", ai_library=False)
    note = Note.objects.create(folder=folder, title="Private", content="Old.")
    apply_note_blocks(edit_block({"id": note.id, "content": "x"}), matter, user)
    note.refresh_from_db()
    assert note.content == "Old."


def test_edit_rejects_never_context_note(user, matter):
    note = Note.objects.create(
        matter=matter, title="Hidden", content="Old.", ai_context="never"
    )
    apply_note_blocks(edit_block({"id": note.id, "content": "x"}), matter, user)
    note.refresh_from_db()
    assert note.content == "Old."


def test_edit_unknown_id_reports(user, matter):
    text = apply_note_blocks(edit_block({"id": 999999, "content": "x"}), matter, user)
    assert "not found or not editable" in text


def test_malformed_edit_left_in_place(user, matter):
    raw = "Done.\n\n```edit-note\n{broken\n```"
    assert apply_note_blocks(raw, matter, user) == raw


# ── Fake confirmation scrubbing ──────────────────────────────────────────────


def test_fake_confirmation_without_block_becomes_notice(user, matter):
    from apps.case.ai.note_blocks import strip_fake_note_confirmations

    raw = "[Aug 09, 2026 03:04 PM] - Created note: **Matter Summary 3** [Analysis]"
    text = strip_fake_note_confirmations(raw)
    assert "Matter Summary 3" not in text
    assert "no note was changed" in text


def test_fake_confirmation_beside_real_block_is_deleted(user, matter):
    from apps.case.ai.note_blocks import strip_fake_note_confirmations

    raw = (
        "- Created note: **Imitation** [Analysis]\n\n"
        '```create-note\n{"title": "Real note", "content": "body"}\n```'
    )
    text = strip_fake_note_confirmations(raw)
    assert "Imitation" not in text
    assert "no note was changed" not in text
    assert "```create-note" in text  # real block untouched, applies next
    applied = apply_note_blocks(text, matter, user)
    assert "Created note: **Real note**" in applied
    assert Note.objects.filter(title="Real note").exists()


def test_ordinary_prose_untouched_by_scrubber(user, matter):
    from apps.case.ai.note_blocks import strip_fake_note_confirmations

    raw = "I previously created note files for you.\nThe note: important."
    assert strip_fake_note_confirmations(raw) == raw
