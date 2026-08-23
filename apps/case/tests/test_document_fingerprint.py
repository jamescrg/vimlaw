"""Duplicate detection on upload: fingerprints and the warning flow."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from apps.case.documents.fingerprint import fingerprint_file
from apps.case.models import Document

pytestmark = pytest.mark.django_db


def make_pdf(text="Hello", title="One"):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_metadata({"/Title": title, "/Producer": f"test-{title}"})
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ── fingerprints ─────────────────────────────────────────────────────────


def test_same_bytes_same_hashes():
    a = fingerprint_file(io.BytesIO(make_pdf()), is_pdf=True)
    b = fingerprint_file(io.BytesIO(make_pdf()), is_pdf=True)
    assert a == b
    assert a[0] and a[1]


def test_metadata_change_keeps_page_fingerprint():
    one = make_pdf(title="One")
    two = make_pdf(title="Two")
    assert one != two
    hash_one, pages_one = fingerprint_file(io.BytesIO(one), is_pdf=True)
    hash_two, pages_two = fingerprint_file(io.BytesIO(two), is_pdf=True)
    assert hash_one != hash_two
    assert pages_one == pages_two


def test_content_change_changes_page_fingerprint():
    _, pages_one = fingerprint_file(io.BytesIO(make_pdf(text="Hello")), is_pdf=True)
    _, pages_two = fingerprint_file(io.BytesIO(make_pdf(text="Bye")), is_pdf=True)
    assert pages_one != pages_two


def test_unreadable_pdf_still_gets_byte_hash():
    content_hash, pages = fingerprint_file(io.BytesIO(b"not a pdf"), is_pdf=True)
    assert content_hash
    assert pages is None


def test_file_is_rewound_after_fingerprinting():
    buf = io.BytesIO(make_pdf())
    fingerprint_file(buf, is_pdf=True)
    assert buf.tell() == 0


# ── model hooks ──────────────────────────────────────────────────────────


def test_save_fingerprints_new_file(matter, user):
    doc = Document(matter=matter, name="A", category="Evidence", created_by=user)
    doc.save()
    doc.file.save("a.pdf", io.BytesIO(make_pdf()), save=True)
    doc.refresh_from_db()
    assert doc.content_hash
    assert doc.page_fingerprint


def test_find_duplicates_excludes_self(matter, user):
    first = Document(matter=matter, name="A", category="Evidence", created_by=user)
    first.save()
    first.file.save("a.pdf", io.BytesIO(make_pdf()), save=True)
    second = Document(matter=matter, name="B", category="Evidence", created_by=user)
    second.save()
    second.file.save("b.pdf", io.BytesIO(make_pdf(title="Other")), save=True)
    assert list(second.find_duplicates()) == [first]
    assert list(first.find_duplicates()) == [second]


# ── upload flow ──────────────────────────────────────────────────────────


def _post(client, matter, pdf_bytes, **extra):
    data = {
        "matter": matter.id,
        "category": "Evidence",
        "name": "Upload",
        "ai_context": "auto",
        "file": SimpleUploadedFile("x.pdf", pdf_bytes, content_type="application/pdf"),
    }
    data.update(extra)
    return client.post(reverse("case:documents-add", args=[matter.id]), data)


def test_first_upload_saves(client_with_matter):
    matter = client_with_matter.matter
    response = _post(client_with_matter, matter, make_pdf())
    assert response.status_code == 204
    assert Document.objects.filter(matter=matter).count() == 1
    doc = Document.objects.get()
    assert doc.content_hash and doc.page_fingerprint


def test_duplicate_upload_warns_then_proceeds(client_with_matter):
    matter = client_with_matter.matter
    assert _post(client_with_matter, matter, make_pdf()).status_code == 204
    first = Document.objects.get()

    # Same pages, different metadata: warned, nothing saved.
    response = _post(client_with_matter, matter, make_pdf(title="Copy"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "already in the system" in body
    assert first.name in body
    assert "same pages, different file metadata" in body
    assert 'name="duplicate_ok"' in body
    assert "Upload anyway" in body
    assert Document.objects.count() == 1

    # Second submit carries duplicate_ok: the copy is stored.
    response = _post(
        client_with_matter, matter, make_pdf(title="Copy"), duplicate_ok="1"
    )
    assert response.status_code == 204
    assert Document.objects.count() == 2


def test_exact_duplicate_has_no_metadata_note(client_with_matter):
    matter = client_with_matter.matter
    _post(client_with_matter, matter, make_pdf())
    response = _post(client_with_matter, matter, make_pdf())
    assert response.status_code == 200
    body = response.content.decode()
    assert "already in the system" in body
    assert "different file metadata" not in body


# ── duplicate badge in the documents table ───────────────────────────────


def test_table_shows_duplicate_badge_linking_to_match(client_with_matter, user):
    matter = client_with_matter.matter
    first = Document(
        matter=matter, name="Original", category="Evidence", created_by=user
    )
    first.save()
    first.file.save("a.pdf", io.BytesIO(make_pdf()), save=True)
    copy = Document(matter=matter, name="Copy", category="Evidence", created_by=user)
    copy.save()
    copy.file.save("b.pdf", io.BytesIO(make_pdf(title="Other")), save=True)

    response = client_with_matter.get(f"/case/{matter.id}/documents/list/")
    assert response.status_code == 200
    body = response.content.decode()
    assert body.count("duplicate-badge") == 2
    assert reverse("case:viewer", args=[first.id]) in body
    assert reverse("case:viewer", args=[copy.id]) in body
    assert "Same pages as &quot;Original&quot;" in body


def test_table_without_duplicates_has_no_badge(client_with_matter, user):
    matter = client_with_matter.matter
    doc = Document(matter=matter, name="Only", category="Evidence", created_by=user)
    doc.save()
    doc.file.save("a.pdf", io.BytesIO(make_pdf()), save=True)
    response = client_with_matter.get(f"/case/{matter.id}/documents/list/")
    assert "duplicate-badge" not in response.content.decode()


def test_cross_matter_copy_is_not_badged(
    client_with_matter, user, contact, practice_area
):
    """A twin filed on another matter is the upload warning's concern;
    the row badge only flags copies within this matter."""
    from apps.matters.models import Matter

    matter = client_with_matter.matter
    other = Matter.objects.create(
        name="Other", client=contact, practice_area=practice_area, status="Open"
    )
    here = Document(matter=matter, name="Here", category="Evidence", created_by=user)
    here.save()
    here.file.save("a.pdf", io.BytesIO(make_pdf()), save=True)
    there = Document(matter=other, name="There", category="Evidence", created_by=user)
    there.save()
    there.file.save("b.pdf", io.BytesIO(make_pdf()), save=True)

    # Both the per-document property and the bulk table path leave it out...
    assert here.duplicates == []
    response = client_with_matter.get(f"/case/{matter.id}/documents/list/")
    assert "duplicate-badge" not in response.content.decode()
    # ...while the system-wide check (the upload warning) still sees it.
    assert list(here.find_duplicates()) == [there]


def test_duplicates_property_uses_bulk_attachment(
    matter, user, django_assert_num_queries
):
    from apps.case.documents.fingerprint import attach_duplicates

    docs = []
    for i in range(3):
        d = Document(matter=matter, name=f"D{i}", category="Evidence", created_by=user)
        d.save()
        d.file.save(f"{i}.pdf", io.BytesIO(make_pdf(text=f"T{i % 2}")), save=True)
        docs.append(d)
    with django_assert_num_queries(1):
        attach_duplicates(docs)
        assert [x.pk for x in docs[0].duplicates] == [docs[2].pk]
        assert docs[1].duplicates == []


# ── dedupe_documents command ─────────────────────────────────────────────


def _doc(matter, user, name, pdf_bytes, **fields):
    doc = Document(
        matter=matter, name=name, category="Evidence", created_by=user, **fields
    )
    doc.save()
    doc.file.save(f"{doc.pk}.pdf", io.BytesIO(pdf_bytes), save=True)
    return doc


def _run_dedupe(*args):
    from django.core.management import call_command

    out = io.StringIO()
    call_command("dedupe_documents", *args, stdout=out, stderr=io.StringIO())
    return out.getvalue()


def test_dedupe_dry_run_reports_without_deleting(matter, user):
    _doc(matter, user, "A", make_pdf())
    _doc(matter, user, "B", make_pdf(title="Copy"))
    out = _run_dedupe()
    assert "keep   " in out and "remove " in out
    assert "Dry run" in out
    assert Document.objects.count() == 2


def test_dedupe_keeps_highlighted_copy_and_removes_file(matter, user):
    from apps.case.models import Highlight

    first = _doc(matter, user, "A", make_pdf())
    second = _doc(matter, user, "B", make_pdf(title="Copy"))
    Highlight.objects.create(
        document=second, slug="hl", text="x", created_by=user, importance=4
    )
    storage, path = first.file.storage, first.file.name
    assert storage.exists(path)

    _run_dedupe("--apply")

    assert list(Document.objects.values_list("pk", flat=True)) == [second.pk]
    assert not storage.exists(path)


def test_dedupe_keeps_oldest_when_nothing_referenced_and_moves_labels(
    matter, user, label
):
    first = _doc(matter, user, "A", make_pdf())
    second = _doc(matter, user, "B", make_pdf(title="Copy"))
    second.labels.add(label)

    _run_dedupe("--apply")

    assert list(Document.objects.values_list("pk", flat=True)) == [first.pk]
    assert list(first.labels.all()) == [label]


def test_dedupe_leaves_cross_matter_copies(matter, user, contact, practice_area):
    from apps.matters.models import Matter

    other = Matter.objects.create(
        name="Other", client=contact, practice_area=practice_area, status="Open"
    )
    _doc(matter, user, "A", make_pdf())
    _doc(other, user, "A again", make_pdf())
    out = _run_dedupe("--apply")
    assert "Across matters (left alone)" in out
    assert Document.objects.count() == 2


def test_dedupe_keeps_every_referenced_copy(matter, user):
    from apps.case.models import Highlight

    a = _doc(matter, user, "A", make_pdf())
    b = _doc(matter, user, "B", make_pdf(title="Copy"))
    for d in (a, b):
        Highlight.objects.create(
            document=d, slug="hl", text="x", created_by=user, importance=4
        )
    _run_dedupe("--apply")
    assert Document.objects.count() == 2


def test_dedupe_hands_drive_identity_to_the_kept_manual_copy(matter, user):
    """The manual upload is referenced (kept); its Drive-mirrored twin is
    removed, but the matter keeps tracking the Drive file: the identity
    moves to the survivor and no tombstone is written (2026-08-03 bucket
    outage made the mirror miss its adoption)."""
    from apps.case.models import Highlight
    from apps.drive.models import DriveRecordTombstone

    manual = _doc(matter, user, "Operating Agreement", make_pdf())
    Highlight.objects.create(
        document=manual, slug="hl", text="x", created_by=user, importance=4
    )
    mirrored = _doc(
        matter,
        user,
        "Operating Agreement",
        make_pdf(),
        drive_file_id="drive-oa",
        drive_path="Evidence/Operating Agreement.pdf",
        drive_modified="2025-01-01T00:00:00.000Z",
    )

    out = _run_dedupe("--apply")
    assert f"remove #{mirrored.pk}" in out
    assert f"Drive identity moves to #{manual.pk}" in out
    assert list(Document.objects.values_list("pk", flat=True)) == [manual.pk]
    manual.refresh_from_db()
    assert manual.drive_file_id == "drive-oa"
    assert manual.drive_path == "Evidence/Operating Agreement.pdf"
    assert manual.drive_modified == "2025-01-01T00:00:00.000Z"
    assert not DriveRecordTombstone.objects.filter(drive_file_id="drive-oa").exists()


def test_dedupe_tombstones_when_no_survivor_can_take_the_drive_identity(matter, user):
    """Two Drive-synced twins (two Drive files with the same bytes): the
    removed one is tombstoned as before, the kept one keeps its own id."""
    from apps.drive.models import DriveRecordTombstone

    first = _doc(matter, user, "A", make_pdf(), drive_file_id="drive-1")
    _doc(matter, user, "A", make_pdf(), drive_file_id="drive-2")
    _run_dedupe("--apply")
    assert list(Document.objects.values_list("pk", flat=True)) == [first.pk]
    first.refresh_from_db()
    assert first.drive_file_id == "drive-1"
    assert DriveRecordTombstone.objects.filter(drive_file_id="drive-2").exists()
