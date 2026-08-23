"""restore_drive_documents: re-fetch mirrored PDFs missing from storage."""

import io

import pytest
from django.core.management import call_command

import apps.drive.google as google
from apps.case.models import Document
from apps.case.tests.test_document_fingerprint import make_pdf

pytestmark = pytest.mark.django_db


def _drive_doc(matter, user, pk_hint, drive_id, pdf):
    doc = Document(
        matter=matter,
        name=f"Doc {pk_hint}",
        category="Evidence",
        created_by=user,
        drive_file_id=drive_id,
        ocr_status="extracted",
        ocr_text="already read",
    )
    doc.save()
    doc.file.save(f"{doc.pk}.pdf", io.BytesIO(pdf), save=True)
    return doc


def test_restores_only_missing_files(matter, user, monkeypatch):
    pdf = make_pdf(text="restore me")
    lost = _drive_doc(matter, user, 1, "drive-lost", pdf)
    kept = _drive_doc(matter, user, 2, "drive-kept", make_pdf(text="still here"))
    # The bytes vanish from storage; the row (and its OCR) stays.
    lost.file.storage.delete(lost.file.name)
    Document.objects.filter(pk=lost.pk).update(content_hash=None, page_fingerprint=None)
    assert not lost.file.storage.exists(lost.file.name)

    downloads = []

    def fake_download(service, meta):
        downloads.append(meta["id"])
        return pdf

    monkeypatch.setattr(google, "build_service", lambda: object())
    monkeypatch.setattr(google, "_download", fake_download)
    queued = []
    monkeypatch.setattr(
        "apps.drive.management.commands.restore_drive_documents._queue_ocr",
        queued.append,
    )

    out = io.StringIO()
    call_command("restore_drive_documents", stdout=out)
    assert downloads == []  # dry run downloads nothing
    assert f"MISSING  {lost.pk:>5}" in out.getvalue()

    out = io.StringIO()
    call_command("restore_drive_documents", "--apply", stdout=out)
    assert downloads == ["drive-lost"]
    lost.refresh_from_db()
    assert lost.file.storage.exists(lost.file.name)
    assert lost.file.name.endswith(f"/{lost.pk}.pdf")
    assert lost.content_hash and lost.page_fingerprint
    assert lost.ocr_status == "extracted" and lost.ocr_text == "already read"
    assert queued == []  # finished OCR is not redone
    assert "Restored 1, failed 0" in out.getvalue()
    assert kept.file.storage.exists(kept.file.name)

    out = io.StringIO()
    call_command("restore_drive_documents", stdout=out)
    assert "Every Drive document is in storage" in out.getvalue()


def test_queues_ocr_when_it_never_finished(matter, user, monkeypatch):
    pdf = make_pdf(text="scan")
    doc = _drive_doc(matter, user, 3, "drive-pending", pdf)
    Document.objects.filter(pk=doc.pk).update(ocr_status="pending", ocr_text=None)
    doc.file.storage.delete(doc.file.name)

    monkeypatch.setattr(google, "build_service", lambda: object())
    monkeypatch.setattr(google, "_download", lambda service, meta: pdf)
    queued = []
    monkeypatch.setattr(
        "apps.drive.management.commands.restore_drive_documents._queue_ocr",
        queued.append,
    )
    call_command("restore_drive_documents", "--apply", stdout=io.StringIO())
    assert queued == [doc.pk]
