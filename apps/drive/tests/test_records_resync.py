"""Per-mapping resync (the Drive Folder modal's save path)."""

import pytest

from apps.case.models import Document
from apps.drive import records
from apps.drive.models import DriveFolderMapping

pytestmark = pytest.mark.django_db


def test_resync_ingests_folder(matter, proceeding, record_mapping, fake_drive):
    fake_drive.add_file("f1", "Complaint.pdf", "rf1")
    fake_drive.add_file("f2", "photo.jpg", "rf1", mime="image/jpeg")
    stats = records.resync_mapping(record_mapping)
    assert stats["records_synced"] == 1
    assert stats["records_non_pdf"] == 1
    doc = Document.objects.get()
    assert doc.proceeding == proceeding
    assert doc.category == "Record"
    assert doc.drive_mapping == record_mapping


def test_resync_idempotent(matter, proceeding, record_mapping, fake_drive):
    fake_drive.add_file("f1", "Complaint.pdf", "rf1")
    records.resync_mapping(record_mapping)
    stats = records.resync_mapping(record_mapping)
    assert stats["records_synced"] == 0
    assert stats["records_unchanged"] == 1


def test_resync_missing_folder_flags_row(
    matter, proceeding, record_mapping, fake_drive
):
    del fake_drive.files_by_id["rf1"]
    stats = records.resync_mapping(record_mapping)
    assert stats["missing"] is True
    record_mapping.refresh_from_db()
    assert record_mapping.missing_since is not None
    assert Document.objects.count() == 0


def test_resync_resolves_legacy_path_to_id(matter, proceeding, fake_drive):
    """A row from the data migration (no folder id) is resolved by its
    cached path on first resync, then keyed by id."""
    mapping = DriveFolderMapping.objects.create(
        matter=matter,
        folder_id=None,
        folder_path="CA-2 Record",
        category="Record",
        proceeding=proceeding,
    )
    fake_drive.add_file("f1", "Complaint.pdf", "rf1")
    stats = records.resync_mapping(mapping)
    assert stats["records_synced"] == 1
    mapping.refresh_from_db()
    assert mapping.folder_id == "rf1"
    fake_drive.rename("rf1", "Record (renamed)")
    assert records.resync_mapping(mapping)["records_unchanged"] == 1


def test_unmapped_row_deleted_keeps_documents(
    matter, proceeding, record_mapping, fake_drive
):
    fake_drive.add_file("f1", "Complaint.pdf", "rf1")
    records.resync_mapping(record_mapping)
    assert Document.objects.count() == 1
    record_mapping.delete()
    doc = Document.objects.get()
    assert doc.drive_mapping is None
    assert doc.category == "Record"
    assert doc.proceeding == proceeding
