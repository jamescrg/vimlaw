"""Key Documents convention: curated evidence ingestion by drag-into-folder."""

import pytest

import apps.drive.google as google
from apps.case.models import Document

pytestmark = pytest.mark.django_db


@pytest.fixture
def evidence_tree(fake_drive):
    """Evidence/Key Documents inside the standard matter folder."""
    fake_drive.add_folder("ef1", "Evidence", parent="mf1")
    fake_drive.add_folder("kd1", "Key Documents", parent="ef1")
    return fake_drive


def test_bootstrap_ingests_key_documents_as_evidence(matter, evidence_tree):
    evidence_tree.add_file("k1", "2026-05-02 Text Thread.pdf", "kd1")
    evidence_tree.add_file("noise1", "random scan.pdf", "ef1")  # outside Key

    stats = google.sync(full=True)

    assert stats["records_synced"] == 1
    doc = Document.objects.get()
    assert doc.matter == matter
    assert doc.proceeding is None
    assert doc.category == "Evidence"
    assert doc.name == "Text Thread"
    assert doc.date.isoformat() == "2026-05-02"
    assert doc.drive_path == (
        "Smith v. Jones/Evidence/Key Documents/2026-05-02 Text Thread.pdf"
    )


def test_key_folder_direct_under_matter_works(matter, fake_drive):
    fake_drive.add_folder("kd2", "Key Documents", parent="mf1")
    fake_drive.add_file("k2", "Exhibit.pdf", "kd2")
    google.sync(full=True)
    assert Document.objects.get().category == "Evidence"


def test_evidence_noise_never_ingested(matter, evidence_tree):
    evidence_tree.add_file("noise1", "dump1.pdf", "ef1")
    evidence_tree.add_folder("sub1", "Photos", parent="ef1")
    evidence_tree.add_file("noise2", "dump2.pdf", "sub1")
    stats = google.sync(full=True)
    assert stats["records_synced"] == 0
    assert Document.objects.count() == 0


def test_incremental_drag_into_key_folder(matter, proceeding, evidence_tree):
    google.sync(full=True)  # cursor
    evidence_tree.add_file("k3", "2026-06-01 Lease.pdf", "kd1")
    evidence_tree.change_feed = [evidence_tree.change_for("k3")]
    stats = google.sync()
    assert stats["records_synced"] == 1
    doc = Document.objects.get(drive_file_id="k3")
    assert doc.category == "Evidence"
    assert doc.proceeding is None


def test_drag_out_leaves_document(matter, evidence_tree):
    meta = evidence_tree.add_file("k1", "Exhibit.pdf", "kd1")
    google.sync(full=True)
    assert Document.objects.count() == 1

    # Dragged back out to the noise pile: the Evidence document stays.
    meta["parents"] = ["ef1"]
    evidence_tree.change_feed = [evidence_tree.change_for("k1")]
    google.sync()
    assert Document.objects.count() == 1


def test_record_folder_wins_over_nested_key_folder(matter, proceeding, fake_drive):
    # A Key Documents folder inside a linked record folder keeps Record
    # semantics (record scope is checked first).
    fake_drive.add_folder("kdr", "Key Documents", parent="rf1")
    fake_drive.add_file("r1", "Order.pdf", "kdr")
    google.sync(full=True)
    doc = Document.objects.get()
    assert doc.category == "Record"
    assert doc.proceeding == proceeding
    assert Document.objects.count() == 1


def test_key_ingest_adopts_manual_twin(matter, evidence_tree):
    from django.core.files.base import ContentFile

    content = b"%PDF-lease"
    manual = Document.objects.create(
        matter=matter, name="Lease", date="2026-06-01", ocr_status="completed"
    )
    manual.file.save(f"{manual.pk}.pdf", ContentFile(content), save=True)

    evidence_tree.add_file("k1", "2026-06-01 Lease.pdf", "kd1", content=content)
    stats = google.sync(full=True)

    assert stats["records_adopted"] == 1
    assert Document.objects.count() == 1
    manual.refresh_from_db()
    assert manual.drive_file_id == "k1"
    assert manual.proceeding is None
    assert manual.category == "Evidence"
