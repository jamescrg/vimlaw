"""Mapped-folder mirror: bootstrap + incremental engine behavior (Record mapping)."""

import pytest

import apps.drive.google as google
from apps.case.models import Document
from apps.drive.models import DriveRecordTombstone
from apps.notes.models import Note

pytestmark = pytest.mark.django_db


def test_bootstrap_ingests_record_pdfs(matter, proceeding, record_mapping, fake_drive):
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
    assert doc.drive_mapping == record_mapping
    assert doc.is_drive_synced
    with doc.file.open("rb") as fh:
        assert fh.read() == b"%PDF-complaint"
    assert fake_drive.ocr_queued == [doc.pk]


def test_bootstrap_idempotent(matter, proceeding, record_mapping, fake_drive):
    fake_drive.add_file("f1", "Complaint.pdf", "rf1")
    google.sync(full=True)
    stats = google.sync(full=True)
    assert stats["records_synced"] == 0
    assert stats["records_unchanged"] == 1
    assert Document.objects.count() == 1


def test_non_pdf_counted_not_ingested(matter, proceeding, record_mapping, fake_drive):
    fake_drive.add_file("f2", "notes.docx", "rf1", mime="application/vnd.something")
    stats = google.sync(full=True)
    assert stats["records_non_pdf"] == 1
    assert Document.objects.count() == 0


def test_unlinked_subfolder_ignored(matter, proceeding, record_mapping, fake_drive):
    fake_drive.add_folder("of1", "Correspondence", parent="mf1")
    fake_drive.add_file("f3", "Letter.pdf", "of1")
    stats = google.sync(full=True)
    assert stats["records_synced"] == 0
    assert Document.objects.count() == 0


def test_nested_subfolder_included(matter, proceeding, record_mapping, fake_drive):
    fake_drive.add_folder("sub1", "Exhibits", parent="rf1")
    fake_drive.add_file("f4", "Exhibit A.pdf", "sub1")
    google.sync(full=True)
    doc = Document.objects.get()
    assert doc.drive_path == "Smith v. Jones/CA-2 Record/Exhibits/Exhibit A.pdf"


def test_missing_record_folder_reported(matter, proceeding, record_mapping, fake_drive):
    del fake_drive.files_by_id["rf1"]
    google.sync(full=True)
    record_mapping.refresh_from_db()
    assert record_mapping.missing_since is not None
    assert google.get_sync_status()["missing_folders"] == ["Smith v. Jones/CA-2 Record"]

    # Folder comes back: the flag clears, nothing was deleted meanwhile.
    fake_drive.add_folder("rf1", "CA-2 Record", parent="mf1")
    google.sync(full=True)
    record_mapping.refresh_from_db()
    assert record_mapping.missing_since is None


def test_incremental_change_ingests(matter, proceeding, record_mapping, fake_drive):
    google.sync(full=True)  # establish cursor
    meta = fake_drive.add_file("f5", "Answer.pdf", "rf1")
    fake_drive.change_feed = [fake_drive.change_for("f5")]
    stats = google.sync()
    assert stats["records_synced"] == 1
    assert Document.objects.get().name == "Answer"
    assert meta["id"] == "f5"


def test_removal_leaves_document_intact(matter, proceeding, record_mapping, fake_drive):
    fake_drive.add_file("f1", "Complaint.pdf", "rf1")
    google.sync(full=True)
    assert Document.objects.count() == 1

    # Deleted in Drive: only a fileId arrives. Append-only mirror keeps it.
    del fake_drive.files_by_id["f1"]
    fake_drive.change_feed = [fake_drive.change_for("f1", removed=True)]
    google.sync()
    assert Document.objects.count() == 1

    # A later full pass keeps it too (no stale reconciliation for records).
    fake_drive.change_feed = []
    google.sync(full=True)
    assert Document.objects.count() == 1


def test_move_out_of_scope_leaves_document(
    matter, proceeding, record_mapping, fake_drive
):
    meta = fake_drive.add_file("f1", "Complaint.pdf", "rf1")
    google.sync(full=True)

    fake_drive.add_folder("of1", "Correspondence", parent="mf1")
    meta["parents"] = ["of1"]
    fake_drive.change_feed = [fake_drive.change_for("f1")]
    google.sync()
    assert Document.objects.count() == 1


def test_modified_file_replaces_bytes_and_resets_ocr(
    matter, proceeding, record_mapping, fake_drive
):
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


def test_tombstone_blocks_reingest(matter, proceeding, record_mapping, fake_drive):
    fake_drive.add_file("f1", "Complaint.pdf", "rf1")
    google.sync(full=True)
    doc = Document.objects.get()

    doc.delete()  # in-app delete: pre_delete signal writes the tombstone
    assert DriveRecordTombstone.objects.filter(drive_file_id="f1").exists()

    fake_drive.change_feed = [fake_drive.change_for("f1")]
    google.sync()
    google.sync(full=True)
    assert Document.objects.count() == 0


def test_notes_mirror_retired(matter, proceeding, record_mapping, fake_drive):
    """Files under Notes/ are ignored, and removals never touch Note rows."""
    fake_drive.add_file(
        "n1",
        "memo.md",
        "nf1",
        mime="text/markdown",
        content=b"# Memo\ncontent",
    )
    google.sync(full=True)
    assert Note.objects.count() == 0

    # App-owned notes survive Drive-side deletions in the changes feed.
    note = Note.objects.create(title="Legacy", matter=matter, content="kept")
    fake_drive.change_feed = [fake_drive.change_for("n1", removed=True)]
    google.sync()
    assert Note.objects.filter(pk=note.pk).exists()


def test_date_prefix_names_the_document(matter, proceeding, record_mapping, fake_drive):
    """The filing convention: '2026-04-29 Complaint.pdf' -> Complaint,
    dated by the prefix (NOT by Drive's UTC createdTime)."""
    fake_drive.add_file(
        "f1",
        "2026-04-29 Complaint.pdf",
        "rf1",
        created="2026-04-30T01:30:00.000Z",  # evening-ET upload: next UTC day
    )
    google.sync(full=True)
    doc = Document.objects.get()
    assert doc.name == "Complaint"
    assert doc.date.isoformat() == "2026-04-29"


def test_no_prefix_falls_back_to_created_time(
    matter, proceeding, record_mapping, fake_drive
):
    fake_drive.add_file("f1", "Complaint.pdf", "rf1")
    google.sync(full=True)
    doc = Document.objects.get()
    assert doc.name == "Complaint"
    assert doc.date.isoformat() == "2026-01-10"


def test_manual_upload_twin_adopted_not_duplicated(
    matter, proceeding, record_mapping, fake_drive
):
    from django.core.files.base import ContentFile

    content = b"%PDF-manual-upload"
    manual = Document.objects.create(
        matter=matter,
        category="Evidence",
        name="Complaint",
        date="2026-04-29",
        ocr_status="completed",
        ocr_text="already extracted",
    )
    manual.file.save(f"{manual.pk}.pdf", ContentFile(content), save=True)

    fake_drive.add_file("f1", "2026-04-29 Complaint.pdf", "rf1", content=content)
    stats = google.sync(full=True)

    assert stats["records_adopted"] == 1
    assert stats["records_synced"] == 0
    assert Document.objects.count() == 1
    manual.refresh_from_db()
    assert manual.drive_file_id == "f1"
    assert manual.proceeding == proceeding
    assert manual.category == "Record"  # follows the folder it was found in
    assert manual.drive_mapping == record_mapping
    assert manual.ocr_status == "completed"  # finished OCR untouched
    assert fake_drive.ocr_queued == []


def test_adoption_skipped_on_size_mismatch(
    matter, proceeding, record_mapping, fake_drive
):
    from django.core.files.base import ContentFile

    manual = Document.objects.create(matter=matter, name="Complaint", date="2026-04-29")
    manual.file.save(
        f"{manual.pk}.pdf", ContentFile(b"%PDF-different-bytes-here"), save=True
    )

    fake_drive.add_file("f1", "2026-04-29 Complaint.pdf", "rf1", content=b"%PDF-drive")
    stats = google.sync(full=True)
    assert stats["records_adopted"] == 0
    assert stats["records_synced"] == 1
    assert Document.objects.count() == 2


def test_adoption_skipped_when_ambiguous(
    matter, proceeding, record_mapping, fake_drive
):
    for _ in range(2):
        Document.objects.create(matter=matter, name="Complaint", date="2026-04-29")
    fake_drive.add_file("f1", "2026-04-29 Complaint.pdf", "rf1")
    stats = google.sync(full=True)
    assert stats["records_adopted"] == 0
    assert stats["records_synced"] == 1
    assert Document.objects.count() == 3
