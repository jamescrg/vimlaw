"""The Documents-tab Link Record Folders modal and guardrails."""

import pytest
from django.urls import reverse

from apps.case.models import Document
from apps.matters.proceedings.models import Proceeding

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _inline_resync(monkeypatch):
    """Record queued resyncs instead of hitting django-q / Drive."""
    calls = []
    monkeypatch.setattr(
        "apps.case.documents.views._queue_resync_proceeding",
        lambda proceeding: calls.append(proceeding.id),
    )
    return calls


def test_modal_lists_proceedings_and_folders(client, matter, proceeding, fake_drive):
    fake_drive.add_folder("of1", "Appeal Record", parent="mf1")
    response = client.get(reverse("case:documents-record-link-modal", args=[matter.id]))
    content = response.content.decode()
    assert "Main" in content
    assert "CA-2 Record" in content
    assert "Appeal Record" in content
    assert "Notes" not in content.replace("Not linked", "")


def test_link_sets_folder_and_queues_resync(
    client, matter, proceeding, fake_drive, _inline_resync
):
    other = Proceeding.objects.create(matter=matter, nickname="Appeal")
    response = client.post(
        reverse("case:documents-record-link", args=[matter.id]),
        {
            f"folder_{proceeding.id}": "CA-2 Record",  # unchanged
            f"folder_{other.id}": "Appeal Record",
        },
    )
    assert response.status_code == 204
    other.refresh_from_db()
    assert other.drive_folder == "Appeal Record"
    # Only the changed link resyncs.
    assert _inline_resync == [other.id]


def test_duplicate_folder_rejected(
    client, matter, proceeding, fake_drive, _inline_resync
):
    other = Proceeding.objects.create(matter=matter, nickname="Appeal")
    response = client.post(
        reverse("case:documents-record-link", args=[matter.id]),
        {
            f"folder_{proceeding.id}": "CA-2 Record",
            f"folder_{other.id}": "CA-2 Record",
        },
    )
    assert response.status_code == 200
    assert "more than one proceeding" in response.content.decode()
    other.refresh_from_db()
    assert other.drive_folder is None
    assert _inline_resync == []


def test_unlink_keeps_documents(client, matter, proceeding, fake_drive, _inline_resync):
    Document.objects.create(
        matter=matter,
        proceeding=proceeding,
        category="Record",
        name="Complaint",
        drive_file_id="f1",
    )
    response = client.post(
        reverse("case:documents-record-link", args=[matter.id]),
        {f"folder_{proceeding.id}": ""},
    )
    assert response.status_code == 204
    proceeding.refresh_from_db()
    assert proceeding.drive_folder is None
    assert Document.objects.count() == 1
    assert _inline_resync == []  # unlink never resyncs (nothing to delete)


def test_edit_blocks_file_replacement_for_synced(
    client, matter, proceeding, fake_drive
):
    from django.core.files.base import ContentFile

    document = Document.objects.create(
        matter=matter,
        proceeding=proceeding,
        category="Record",
        name="Complaint",
        drive_file_id="f1",
    )
    document.file.save("1.pdf", ContentFile(b"%PDF-original"), save=True)

    response = client.post(
        reverse("case:documents-edit", args=[document.id]),
        {
            "name": "Complaint",
            "category": "Record",
            "importance": 4,
            "ai_context": "auto",
            "file": ContentFile(b"%PDF-replacement", name="new.pdf"),
        },
    )
    assert "synced from Google Drive" in response.content.decode()
    with document.file.open("rb") as fh:
        assert fh.read() == b"%PDF-original"
