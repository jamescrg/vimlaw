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
