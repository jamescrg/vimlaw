"""Record-folder mirror: bootstrap + incremental engine behavior."""

import pytest

import apps.drive.google as google
from apps.case.models import Document
from apps.drive.models import DriveRecordTombstone, DriveSyncState
from apps.notes.models import Note

pytestmark = pytest.mark.django_db


def _state():
    return DriveSyncState.objects.get(pk=1)


def test_bootstrap_ingests_record_pdfs(matter, proceeding, fake_drive):
    fake_drive.add_file("f1", "Complaint.pdf", "rf1", content=b"%PDF-complaint")
    stats = google.sync(full=True)

    assert stats["records_synced"] == 1
    doc = Document.objects.get()
    assert doc.matter == matter
    assert doc.proceeding == proceeding
    assert doc.category == "Record"
    assert doc.name == "Complaint"
    assert doc.date.isoformat() == "2026-01-10"
    assert doc.drive_file_id == "f1"
    assert doc.drive_path == "Smith v. Jones/CA-2 Record/Complaint.pdf"
    assert doc.is_drive_synced
    with doc.file.open("rb") as fh:
        assert fh.read() == b"%PDF-complaint"
    assert fake_drive.ocr_queued == [doc.pk]


def test_bootstrap_idempotent(matter, proceeding, fake_drive):
    fake_drive.add_file("f1", "Complaint.pdf", "rf1")
    google.sync(full=True)
    stats = google.sync(full=True)
    assert stats["records_synced"] == 0
    assert stats["records_unchanged"] == 1
    assert Document.objects.count() == 1


def test_non_pdf_counted_not_ingested(matter, proceeding, fake_drive):
    fake_drive.add_file("f2", "notes.docx", "rf1", mime="application/vnd.something")
    stats = google.sync(full=True)
    assert stats["records_non_pdf"] == 1
    assert Document.objects.count() == 0


def test_unlinked_subfolder_ignored(matter, proceeding, fake_drive):
    fake_drive.add_folder("of1", "Correspondence", parent="mf1")
    fake_drive.add_file("f3", "Letter.pdf", "of1")
    stats = google.sync(full=True)
    assert stats["records_synced"] == 0
    assert Document.objects.count() == 0


def test_nested_subfolder_included(matter, proceeding, fake_drive):
    fake_drive.add_folder("sub1", "Exhibits", parent="rf1")
    fake_drive.add_file("f4", "Exhibit A.pdf", "sub1")
    google.sync(full=True)
    doc = Document.objects.get()
    assert doc.drive_path == "Smith v. Jones/CA-2 Record/Exhibits/Exhibit A.pdf"


def test_missing_record_folder_reported(matter, proceeding, fake_drive):
    del fake_drive.files_by_id["rf1"]
    stats = google.sync(full=True)
    assert stats["missing_record_folders"] == ["Smith v. Jones/CA-2 Record"]
    assert _state().missing_record_folders == ["Smith v. Jones/CA-2 Record"]


def test_incremental_change_ingests(matter, proceeding, fake_drive):
    google.sync(full=True)  # establish cursor
    meta = fake_drive.add_file("f5", "Answer.pdf", "rf1")
    fake_drive.change_feed = [fake_drive.change_for("f5")]
    stats = google.sync()
    assert stats["records_synced"] == 1
    assert Document.objects.get().name == "Answer"
    assert meta["id"] == "f5"


def test_removal_leaves_document_intact(matter, proceeding, fake_drive):
    fake_drive.add_file("f1", "Complaint.pdf", "rf1")
    google.sync(full=True)
    assert Document.objects.count() == 1

    # Deleted in Drive: only a fileId arrives. Append-only mirror keeps it.
    del fake_drive.files_by_id["f1"]
    fake_drive.change_feed = [fake_drive.change_for("f1", removed=True)]
    stats = google.sync()
    assert stats["removed"] == 0
    assert Document.objects.count() == 1

    # A later full pass keeps it too (no stale reconciliation for records).
    fake_drive.change_feed = []
    google.sync(full=True)
    assert Document.objects.count() == 1


def test_move_out_of_scope_leaves_document(matter, proceeding, fake_drive):
    meta = fake_drive.add_file("f1", "Complaint.pdf", "rf1")
    google.sync(full=True)

    fake_drive.add_folder("of1", "Correspondence", parent="mf1")
    meta["parents"] = ["of1"]
    fake_drive.change_feed = [fake_drive.change_for("f1")]
    google.sync()
    assert Document.objects.count() == 1


def test_modified_file_replaces_bytes_and_resets_ocr(matter, proceeding, fake_drive):
    meta = fake_drive.add_file("f1", "Complaint.pdf", "rf1")
    google.sync(full=True)
    doc = Document.objects.get()
    doc.name = "Amended Complaint (my title)"
    doc.importance = 7
    doc.ocr_status = "completed"
    doc.ocr_text = "old text"
    doc.save()

    meta["modifiedTime"] = "2026-02-01T00:00:00.000Z"
    meta["content"] = b"%PDF-corrected"
    fake_drive.change_feed = [fake_drive.change_for("f1")]
    stats = google.sync()

    assert stats["records_updated"] == 1
    doc.refresh_from_db()
    with doc.file.open("rb") as fh:
        assert fh.read() == b"%PDF-corrected"
    assert doc.ocr_status == "pending"
    assert doc.ocr_text is None
    # User-set metadata untouched.
    assert doc.name == "Amended Complaint (my title)"
    assert doc.importance == 7
    assert doc.drive_modified == "2026-02-01T00:00:00.000Z"


def test_tombstone_blocks_reingest(matter, proceeding, fake_drive):
    fake_drive.add_file("f1", "Complaint.pdf", "rf1")
    google.sync(full=True)
    doc = Document.objects.get()

    doc.delete()  # in-app delete: pre_delete signal writes the tombstone
    assert DriveRecordTombstone.objects.filter(drive_file_id="f1").exists()

    fake_drive.change_feed = [fake_drive.change_for("f1")]
    google.sync()
    google.sync(full=True)
    assert Document.objects.count() == 0


def test_notes_regression_sync_and_removal(matter, proceeding, fake_drive):
    """The notes mirror keeps its exact semantics beside the record path."""
    fake_drive.add_file(
        "n1",
        "memo.md",
        "nf1",
        mime="text/markdown",
        content=b"# Memo\ncontent",
    )
    stats = google.sync(full=True)
    assert stats["converted"] == 1
    note = Note.objects.get(drive_file_id="n1")
    assert note.matter == matter

    # Note removal still deletes the Note (unlike record Documents).
    del fake_drive.files_by_id["n1"]
    fake_drive.change_feed = [fake_drive.change_for("n1", removed=True)]
    stats = google.sync()
    assert stats["removed"] == 1
    assert not Note.objects.filter(drive_file_id="n1").exists()
