"""Per-proceeding resync (the link modal's Link & Sync path)."""

import pytest

from apps.case.models import Document
from apps.drive import records

pytestmark = pytest.mark.django_db


def test_resync_ingests_folder(matter, proceeding, fake_drive):
    fake_drive.add_file("f1", "Complaint.pdf", "rf1")
    fake_drive.add_file("f2", "photo.jpg", "rf1", mime="image/jpeg")
    stats = records.resync_proceeding(proceeding)
    assert stats["records_synced"] == 1
    assert stats["records_non_pdf"] == 1
    assert Document.objects.get().proceeding == proceeding


def test_resync_idempotent(matter, proceeding, fake_drive):
    fake_drive.add_file("f1", "Complaint.pdf", "rf1")
    records.resync_proceeding(proceeding)
    stats = records.resync_proceeding(proceeding)
    assert stats["records_synced"] == 0
    assert stats["records_unchanged"] == 1


def test_resync_missing_folder_no_crash(matter, proceeding, fake_drive):
    proceeding.drive_folder = "No Such Folder"
    proceeding.save()
    stats = records.resync_proceeding(proceeding)
    assert stats["missing"] is True
    assert Document.objects.count() == 0


def test_resync_unlinked_noops_and_keeps_documents(matter, proceeding, fake_drive):
    fake_drive.add_file("f1", "Complaint.pdf", "rf1")
    records.resync_proceeding(proceeding)
    assert Document.objects.count() == 1

    proceeding.drive_folder = None
    proceeding.save()
    assert records.resync_proceeding(proceeding) is None
    assert Document.objects.count() == 1


def test_list_record_subfolders_excludes_notes(matter, fake_drive):
    fake_drive.add_folder("of1", "Correspondence", parent="mf1")
    assert records.list_record_subfolders(matter) == [
        "CA-2 Record",
        "Correspondence",
    ]
