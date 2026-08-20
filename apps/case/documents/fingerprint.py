"""Content fingerprints for duplicate detection on upload.

Two fingerprints per document, both SHA-256 hex digests:

- ``content_hash``: the file bytes as stored. Catches the same file
  uploaded twice (to one matter or to two), which is the common case.
- ``page_fingerprint`` (PDFs only): the page content only, with the
  document metadata left out. The Info dictionary, XMP metadata, the
  trailer /ID, the cross-reference layout and object numbering all vary
  when a PDF is re-saved or has its title or dates edited without the
  pages changing; this digest covers the page count plus every page's
  decoded content stream and the raw (encoded) data of the XObjects
  (images, forms) it draws, so two such files compare equal. Fonts and
  annotations are not hashed.

Either fingerprint matching an existing document marks the upload as a
duplicate; the UI warns and lets the user proceed.
"""

import hashlib
import logging

from django.db.models import Q

logger = logging.getLogger(__name__)

_CHUNK = 1024 * 1024
# Above this size the page fingerprint is skipped; the byte hash still runs.
PAGE_FINGERPRINT_MAX_BYTES = 150 * 1024 * 1024
_FORM_XOBJECT_DEPTH = 3


def _rewind(fileobj):
    try:
        fileobj.seek(0)
    except (AttributeError, OSError):
        pass


def file_sha256(fileobj) -> str:
    """SHA-256 of the file's bytes; leaves the file rewound to the start."""
    _rewind(fileobj)
    digest = hashlib.sha256()
    for chunk in iter(lambda: fileobj.read(_CHUNK), b""):
        digest.update(chunk)
    _rewind(fileobj)
    return digest.hexdigest()


def _hash_xobjects(resources, digest, depth):
    """Feed the raw data of every XObject under ``resources`` to ``digest``."""
    if not resources or depth > _FORM_XOBJECT_DEPTH:
        return
    try:
        xobjects = resources.get("/XObject")
        xobjects = xobjects.get_object() if xobjects is not None else None
    except Exception:
        return
    if not xobjects:
        return
    for key in sorted(xobjects.keys()):
        try:
            obj = xobjects[key].get_object()
        except Exception:
            continue
        digest.update(str(key).encode())
        # Raw (still-encoded) stream bytes on purpose: decoding images via
        # get_data() runs pypdf's pure-Python filters and took 79s for five
        # pages of a scanned filing; the raw bytes of all fifty took 0.14s.
        # A copy whose images were recompressed therefore reads as a
        # different document, which is acceptable.
        raw = getattr(obj, "_data", None)
        if raw:
            digest.update(raw)
        if obj.get("/Subtype") == "/Form":
            _hash_xobjects(obj.get("/Resources"), digest, depth + 1)


def pdf_page_fingerprint(fileobj) -> str | None:
    """Metadata-agnostic digest of a PDF's pages, or None if unreadable."""
    from pypdf import PdfReader

    _rewind(fileobj)
    try:
        reader = PdfReader(fileobj)
        digest = hashlib.sha256()
        pages = reader.pages
        digest.update(f"pages:{len(pages)}".encode())
        for index, page in enumerate(pages):
            digest.update(f"page:{index}".encode())
            contents = page.get_contents()
            if contents is not None:
                digest.update(contents.get_data())
            _hash_xobjects(page.get("/Resources"), digest, 0)
        return digest.hexdigest()
    except Exception as exc:
        logger.info("Page fingerprint unavailable: %s", exc)
        return None
    finally:
        _rewind(fileobj)


def fingerprint_file(fileobj, *, is_pdf: bool, size: int | None = None):
    """Return (content_hash, page_fingerprint) for an open binary file."""
    content_hash = file_sha256(fileobj)
    page_fingerprint = None
    if is_pdf and (size is None or size <= PAGE_FINGERPRINT_MAX_BYTES):
        page_fingerprint = pdf_page_fingerprint(fileobj)
    return content_hash, page_fingerprint


def find_duplicates(content_hash, page_fingerprint=None, exclude_pk=None):
    """Documents whose bytes or page content match, newest first."""
    from apps.case.models import Document

    if not content_hash and not page_fingerprint:
        return Document.objects.none()
    query = Q()
    if content_hash:
        query |= Q(content_hash=content_hash)
    if page_fingerprint:
        query |= Q(page_fingerprint=page_fingerprint)
    queryset = Document.objects.filter(query).select_related("matter")
    if exclude_pk:
        queryset = queryset.exclude(pk=exclude_pk)
    return queryset.order_by("-created_at")


def attach_duplicates(documents):
    """Set ``_duplicates`` on each document in one query.

    Used by the documents table so every row can show its duplicate badge
    without a query per row; ``Document.duplicates`` reads the attribute
    and falls back to a per-document query when it is absent (single-row
    re-renders).
    """
    from apps.case.models import Document

    documents = list(documents)
    hashes = {d.content_hash for d in documents if d.content_hash}
    pages = {d.page_fingerprint for d in documents if d.page_fingerprint}
    for doc in documents:
        doc._duplicates = []
    if not hashes and not pages:
        return documents
    query = Q()
    if hashes:
        query |= Q(content_hash__in=hashes)
    if pages:
        query |= Q(page_fingerprint__in=pages)
    matches = list(
        Document.objects.filter(query).select_related("matter").order_by("-created_at")
    )
    for doc in documents:
        doc._duplicates = [
            m
            for m in matches
            if m.pk != doc.pk
            and (
                (doc.content_hash and m.content_hash == doc.content_hash)
                or (doc.page_fingerprint and m.page_fingerprint == doc.page_fingerprint)
            )
        ]
    return documents
