"""Note folder handling when Drive-synced notes move between matters.

A synced note keeps a manually assigned NoteFolder across normal re-syncs
(folder is app-only metadata), but when the Drive file moves to a DIFFERENT
matter's folder, the note's folder must reset — the old matter's folder is
out of scope in the new matter.
"""

from unittest.mock import patch

import pytest

from apps.drive.google import _ingest
from apps.notes.models import Note, NoteFolder

pytestmark = pytest.mark.django_db

MTIME = "2026-01-01T00:00:00.000Z"


def _meta(fid="f1", name="Memo.docx", mtime=MTIME):
    return {"id": fid, "name": name, "modifiedTime": mtime}


def _run(meta, parts, matters, dry_run=False):
    stats = {"skipped": 0, "converted": 0, "would-convert": 0}
    with (
        patch("apps.drive.google._download", return_value=b""),
        patch("apps.drive.google.convert.to_markdown", return_value="body"),
    ):
        _ingest(None, meta, parts, matters, None, dry_run, stats, set())
    return stats


@pytest.fixture
def synced_note(matter):
    folder = NoteFolder.objects.create(name="Filed", matter=matter)
    return Note.objects.create(
        title="Memo",
        matter=matter,
        folder=folder,
        drive_file_id="f1",
        drive_path="A/Notes/Memo.docx",
        drive_modified=MTIME,
    )


def _other_matter(matter):
    return matter.__class__.objects.create(name="Other Matter", status="Open")


def test_same_matter_resync_keeps_manual_folder(synced_note, matter):
    _run(_meta(), ["A", "Notes", "Memo.docx"], {"A": matter})
    synced_note.refresh_from_db()
    assert synced_note.folder is not None  # manual assignment survives


def test_unchanged_content_matter_move_resets_folder(synced_note, matter):
    other = _other_matter(matter)
    _run(_meta(), ["B", "Notes", "Memo.docx"], {"B": other})
    synced_note.refresh_from_db()
    assert synced_note.matter_id == other.id
    assert synced_note.folder_id is None


def test_changed_content_matter_move_resets_folder(synced_note, matter):
    other = _other_matter(matter)
    _run(
        _meta(mtime="2026-02-02T00:00:00.000Z"),
        ["B", "Notes", "Memo.docx"],
        {"B": other},
    )
    synced_note.refresh_from_db()
    assert synced_note.matter_id == other.id
    assert synced_note.folder_id is None


def test_changed_content_same_matter_keeps_folder(synced_note, matter):
    _run(
        _meta(mtime="2026-02-02T00:00:00.000Z"),
        ["A", "Notes", "Memo.docx"],
        {"A": matter},
    )
    synced_note.refresh_from_db()
    assert synced_note.matter_id == matter.id
    assert synced_note.folder is not None
