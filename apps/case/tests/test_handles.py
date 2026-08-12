"""Tests for raw context-handle translation (handles.py)."""

import pytest

from apps.case.ai.handles import resolve_handles_for_chat, resolve_handles_for_note
from apps.notes.models import Note, NoteFolder

pytestmark = pytest.mark.django_db


# ── Chat: handles become markdown links ──────────────────────────────────────


def test_chat_doc_handle_becomes_link(matter, document):
    text = resolve_handles_for_chat(f"See [doc:{document.id}] for terms.", matter)
    assert (
        text == f"See [Test Document](/case/documents/{document.id}/view/) for terms."
    )


def test_chat_hl_handle_becomes_link(matter, highlight):
    text = resolve_handles_for_chat(f"Per [hl:{highlight.id}].", matter)
    assert f"](/case/highlights/{highlight.id}/link/)" in text
    assert "[hl:" not in text


def test_chat_note_handle_becomes_link(matter):
    note = Note.objects.create(matter=matter, title="Service memo", content="x")
    text = resolve_handles_for_chat(f"As noted in [note:{note.id}].", matter)
    assert text == f"As noted in [Service memo](/case/notes/{note.id}/)."


def test_chat_library_note_links_to_notes_app(matter):
    folder = NoteFolder.objects.create(name="Library")
    note = Note.objects.create(folder=folder, title="Guide", content="x")
    text = resolve_handles_for_chat(f"[note:{note.id}]", matter)
    assert text == f"[Guide](/notes/{note.id}/)"


def test_chat_unknown_handle_omitted(matter):
    assert resolve_handles_for_chat("See [doc:999999].", matter) == "See ."


def test_chat_cross_matter_doc_omitted(matter, document, contact, practice_area):
    from apps.matters.models import Matter

    other = Matter.objects.create(
        name="Other", client=contact, practice_area=practice_area
    )
    assert resolve_handles_for_chat(f"[doc:{document.id}]", other) == ""


def test_chat_label_brackets_stripped(matter, document):
    document.name = "Exhibit [A] | Contract"
    document.save()
    text = resolve_handles_for_chat(f"[doc:{document.id}]", matter)
    assert text == f"[Exhibit A  Contract](/case/documents/{document.id}/view/)"


# ── Notes: handles become reference chips ────────────────────────────────────


def test_note_doc_handle_becomes_chip(matter, document):
    text = resolve_handles_for_note(f"Terms in [doc:{document.id}].", matter)
    assert text == f"Terms in [[doc:{document.id}|Test Document]]."


def test_note_hl_handle_becomes_chip(matter, highlight):
    text = resolve_handles_for_note(f"Per [hl:{highlight.id}].", matter)
    assert text.startswith(f"Per [[hl:{highlight.id}|")
    assert text.endswith("]].")


def test_note_note_handle_becomes_title(matter):
    note = Note.objects.create(matter=matter, title="Service memo", content="x")
    text = resolve_handles_for_note(f"See [note:{note.id}].", matter)
    assert text == "See Service memo."


def test_note_unknown_handle_omitted(matter):
    assert resolve_handles_for_note("See [hl:999999].", matter) == "See ."


def test_note_markdown_hl_link_becomes_chip(matter, highlight):
    text = resolve_handles_for_note(
        f"Service failed. [Smith Dep. p.34](/case/highlights/{highlight.id}/link/)",
        matter,
    )
    assert text == f"Service failed. [[hl:{highlight.id}|Smith Dep. p.34]]"


def test_note_markdown_doc_link_becomes_chip(matter, document):
    text = resolve_handles_for_note(
        f"Signed. [Engagement Letter](/case/documents/{document.id}/view/)", matter
    )
    assert text == f"Signed. [[doc:{document.id}|Engagement Letter]]"


def test_note_markdown_link_bad_id_omitted(matter):
    text = resolve_handles_for_note(
        "Signed. [Letter](/case/documents/999999/view/)", matter
    )
    assert text == "Signed. "


def test_note_ordinary_markdown_link_untouched(matter):
    text = "See [the statute](https://law.example.com/ocga)."
    assert resolve_handles_for_note(text, matter) == text


# ── Invented pseudo-handles stripped in both directions ──────────────────────


def test_pseudo_fact_handle_stripped(matter):
    text = "C&B issued a 10-day notice [fact:2026-03-17]."
    assert resolve_handles_for_note(text, matter) == "C&B issued a 10-day notice."
    assert resolve_handles_for_chat(text, matter) == "C&B issued a 10-day notice."


def test_pseudo_task_handle_stripped(matter):
    assert resolve_handles_for_chat("Done [task:12].", matter) == "Done."


def test_bracketed_prose_not_stripped(matter):
    text = "The [Fact Sheet] and [sic] remain."
    assert resolve_handles_for_chat(text, matter) == text
