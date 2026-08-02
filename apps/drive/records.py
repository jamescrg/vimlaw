"""Google Drive document mirrors: record folders and Key Documents.

PDFs filed in a proceeding's linked record folder (``Proceeding.drive_folder``,
a subfolder of the matter's Drive folder) sync in as Record ``Document`` rows
on that matter+proceeding: OCR'd, searchable, highlightable, AI-visible.

PDFs dragged into any folder named per settings.DRIVE_KEY_DOCUMENTS_FOLDER
("Key Documents") inside a matter's folder sync in the same way as Evidence
documents with no proceeding — the drag IS the curation gesture, so the
evidence folder at large stays uningested noise while its keepers flow in.

Contract (deliberately different from the notes mirror):
- Append-only. Drive-side deletions, trashes and moves NEVER remove a
  Document; the record can only shrink through a deliberate in-app delete,
  which tombstones the Drive file id so the file doesn't boomerang back
  (``DriveRecordTombstone``, written by a pre_delete signal).
- PDFs only. Anything else in a linked folder is counted, not ingested.
- Modified files are refreshed (bytes replaced, OCR reset and re-queued);
  user-set metadata (name, date, description, importance, labels, AI
  settings, highlights) is never touched after the first ingest.

``apps.drive.google.sync()`` stays the single consumer of the drive-wide
changes feed and dispatches in-scope files here.
"""

import logging
import os
import re
from datetime import datetime

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone
from googleapiclient.errors import HttpError

from apps.case.models import Document
from apps.matters.proceedings.models import Proceeding

from . import google
from .models import DriveRecordTombstone

logger = logging.getLogger(__name__)

PDF_MIME = "application/pdf"

RECORD_STAT_KEYS = (
    "records_synced",
    "records_adopted",
    "records_updated",
    "records_unchanged",
    "records_non_pdf",
    "records_failed",
)

# The filing convention the upload form also parses (file-upload-forms.js):
# an ISO date prefix names the document's date and is sliced off the name.
_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[\s\-_]*")


def new_record_stats():
    return {key: 0 for key in RECORD_STAT_KEYS}


def proceedings_by_folder():
    """Map (matter_folder, record_folder) -> Proceeding for linked pairs.

    Only proceedings whose matter also has a linked Drive folder can be in
    scope: the record folder lives inside the matter folder.
    """
    qs = (
        Proceeding.objects.exclude(drive_folder__isnull=True)
        .exclude(drive_folder="")
        .select_related("matter")
    )
    return {
        (p.matter.drive_folder, p.drive_folder): p
        for p in qs
        if p.matter and p.matter.drive_folder
    }


def is_pdf(file_meta):
    return (
        file_meta.get("mimeType") == PDF_MIME
        or os.path.splitext(file_meta.get("name", ""))[1].lower() == ".pdf"
    )


def in_record_scope(parts, links):
    """True when path parts land inside a linked record folder.

    Only the first two segments matter (matter folder / record folder), so
    subfolders nested inside a record folder are included, same as the
    notes scope test.
    """
    return bool(parts) and len(parts) >= 3 and (parts[0], parts[1]) in links


def key_folder_name():
    """The convention folder name for curated evidence ("Key Documents")."""
    return settings.DRIVE_KEY_DOCUMENTS_FOLDER


def in_key_scope(parts, matters):
    """True when path parts land inside a matter's Key Documents folder.

    Pure convention, no linking: any folder with the configured name, at
    any depth inside a linked matter's folder (e.g. Evidence/Key
    Documents), is a curated ingestion point — dragging a PDF in adds it
    to the app as Evidence. Checked AFTER the notes and record scopes in
    the dispatch, so a Key Documents folder nested inside those keeps
    their semantics.
    """
    name = key_folder_name()
    return (
        bool(name)
        and bool(parts)
        and len(parts) >= 3
        and parts[0] in matters
        and name in parts[1:-1]
    )


def _created_date(file_meta):
    created = file_meta.get("createdTime") or ""
    try:
        return datetime.fromisoformat(created.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _name_and_date(file_meta):
    """Document name + date from the filename, per the filing convention.

    "2026-04-29 Complaint.pdf" -> ("Complaint", date(2026, 4, 29)), exactly
    as the upload form does. Without a (valid) date prefix, the full stem is
    the name and Drive's createdTime is the fallback date — which is the
    UTC upload moment, so the prefix always wins when present (createdTime
    lands a day off for anything filed in the evening).
    """
    stem = os.path.splitext(file_meta.get("name", ""))[0]
    match = _DATE_PREFIX_RE.match(stem)
    if match:
        try:
            date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        except ValueError:
            date = None
        if date:
            name = stem[match.end() :].strip() or stem
            return name[:255], date
    return stem[:255], _created_date(file_meta)


def _meta_size(file_meta):
    try:
        return int(file_meta.get("size") or 0)
    except (TypeError, ValueError):
        return 0


def _adopt_candidate(matter, name, date, size):
    """A manually-uploaded twin of this Drive file, if one is identifiable.

    Deliberately conservative heuristic: same matter, not already
    Drive-synced, same name (case-insensitive), same date, and — when both
    sizes are known — the same byte size. Exactly one match adopts;
    ambiguity or any mismatch creates a new row instead of guessing.
    """
    qs = Document.objects.filter(
        matter=matter,
        drive_file_id__isnull=True,
        name__iexact=name,
        date=date,
    )
    candidates = list(qs[:2])
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    if size and candidate.file:
        try:
            if candidate.file.size != size:
                return None
        except Exception:
            # Storage hiccup on the size check: don't guess, don't adopt.
            return None
    return candidate


def _reset_ocr(document):
    """Mirror documents_edit's file-replacement OCR reset."""
    document.ocr_status = "pending"
    document.ocr_text = None
    document.ocr_error = None
    document.ocr_processed_at = None
    document.page_count = None
    document.ocr_pages_done = 0


def _queue_ocr(document_id):
    """Queue OCR explicitly (mirrors promote_email): the post_save signal
    only fires on the file-less first save, so it never sees the PDF."""
    try:
        from django_q.tasks import async_task

        async_task(
            "apps.case.documents.tasks.process_document_ocr",
            document_id,
            task_name=f"OCR-{document_id}",
            group="ocr_processing",
        )
    except Exception:
        from apps.case.documents.tasks import process_document_ocr

        process_document_ocr(document_id)


def ingest_record(service, file_meta, parts, links, dry_run, stats):
    """Upsert one record-folder PDF (Record category, linked proceeding)."""
    proceeding = links[(parts[0], parts[1])]
    ingest_pdf(
        service,
        file_meta,
        parts,
        proceeding.matter,
        proceeding,
        "Record",
        dry_run,
        stats,
    )


def ingest_pdf(service, file_meta, parts, matter, proceeding, category, dry_run, stats):
    """Upsert one Drive PDF as a Document (tombstoned ids are skipped).

    ``proceeding`` may be None (Key Documents ingest: category Evidence,
    no proceeding); a proceeding a user has assigned by hand is then never
    overwritten on refresh.
    """
    fid = file_meta["id"]
    mtime = file_meta.get("modifiedTime")
    rel_path = "/".join(parts)[:1024]

    if DriveRecordTombstone.objects.filter(drive_file_id=fid).exists():
        return

    existing = Document.objects.filter(drive_file_id=fid).first()

    if existing and existing.drive_modified == mtime:
        # Bytes unchanged; refresh provenance if the file merely moved
        # between ingestion folders.
        moved = (
            existing.drive_path != rel_path
            or existing.matter_id != matter.id
            or (proceeding is not None and existing.proceeding_id != proceeding.id)
        )
        if not dry_run and moved:
            existing.drive_path = rel_path
            existing.matter = matter
            if proceeding is not None:
                existing.proceeding = proceeding
            existing.drive_synced_at = timezone.now()
            existing.save(
                update_fields=[
                    "drive_path",
                    "proceeding",
                    "matter",
                    "drive_synced_at",
                ]
            )
        stats["records_unchanged"] += 1
        return

    if dry_run:
        stats["records_updated" if existing else "records_synced"] += 1
        return

    name, date = _name_and_date(file_meta)

    if not existing:
        # A manually-uploaded twin (same name, date and size) adopts the
        # Drive identity instead of becoming a duplicate: provenance is
        # attached, bytes and finished OCR stay as they are.
        candidate = _adopt_candidate(matter, name, date, _meta_size(file_meta))
        if candidate:
            if proceeding is not None:
                candidate.proceeding = proceeding
            candidate.drive_file_id = fid
            candidate.drive_path = rel_path
            candidate.drive_modified = mtime
            candidate.drive_synced_at = timezone.now()
            candidate.save()
            stats["records_adopted"] += 1
            return

    content = google._download(service, file_meta)

    if existing:
        # Corrected scan etc.: replace the bytes and redo OCR, but never
        # touch user-set metadata. Highlights are kept (page layout of a
        # corrected filing rarely shifts; re-check them if it does).
        if existing.file:
            default_storage.delete(existing.file.name)
        existing.file.save(f"{existing.pk}.pdf", ContentFile(content), save=False)
        _reset_ocr(existing)
        if proceeding is not None:
            existing.proceeding = proceeding
        existing.matter = matter
        existing.drive_path = rel_path
        existing.drive_modified = mtime
        existing.drive_synced_at = timezone.now()
        existing.save()
        _queue_ocr(existing.pk)
        stats["records_updated"] += 1
        return

    document = Document(
        matter=matter,
        proceeding=proceeding,
        category=category,
        name=name,
        date=date,
        drive_file_id=fid,
        drive_path=rel_path,
        drive_modified=mtime,
        drive_synced_at=timezone.now(),
    )
    document.save()
    document.file.save(f"{document.pk}.pdf", ContentFile(content), save=True)

    if not document.file.storage.exists(document.file.name):
        # Storage write failed: undo the row, and also the tombstone the
        # pre_delete signal just wrote (this was cleanup, not a human
        # delete — the file must remain ingestable on the next pass).
        document.delete()
        DriveRecordTombstone.objects.filter(drive_file_id=fid).delete()
        raise RuntimeError(f"Record PDF did not save to storage (Drive {fid}).")

    _queue_ocr(document.pk)
    stats["records_synced"] += 1


def resync_proceeding(proceeding):
    """Ingest one proceeding's linked record folder (link created/changed).

    Never deletes anything: unlinking a folder, or a folder that no longer
    exists, leaves already-synced Documents in place. Returns a stats dict
    (with ``missing: True`` when the folder wasn't found), or None when
    Drive or the link chain isn't set up.
    """
    matter = proceeding.matter
    if not google.check_credentials():
        return None
    if not proceeding.drive_folder or matter is None or not matter.drive_folder:
        return None

    service = google.build_service()
    root_id = google._find_root_folder(service)
    if not root_id:
        return None

    stats = new_record_stats()
    matter_folder = google._find_child_folder(service, root_id, matter.drive_folder)
    record_folder = (
        google._find_child_folder(service, matter_folder["id"], proceeding.drive_folder)
        if matter_folder
        else None
    )
    if record_folder is None:
        logger.warning(
            "Record folder %r not found for proceeding %s",
            proceeding.drive_folder,
            proceeding.pk,
        )
        return {**stats, "missing": True}

    links = {(matter.drive_folder, proceeding.drive_folder): proceeding}
    stack = [(record_folder["id"], [matter.drive_folder, proceeding.drive_folder])]
    while stack:
        folder_id, prefix = stack.pop()
        for child in google._list_children(service, folder_id):
            if child.get("mimeType") == google.FOLDER_MIME:
                stack.append((child["id"], prefix + [child["name"]]))
                continue
            if not is_pdf(child):
                stats["records_non_pdf"] += 1
                continue
            try:
                ingest_record(
                    service, child, prefix + [child["name"]], links, False, stats
                )
            except Exception:
                stats["records_failed"] += 1
                logger.exception(
                    "Failed to sync record %s for proceeding %s",
                    child.get("name"),
                    proceeding.pk,
                )
    return stats


def resync_proceeding_by_id(proceeding_id):
    """async_task entry point for the record-link views."""
    proceeding = (
        Proceeding.objects.filter(pk=proceeding_id).select_related("matter").first()
    )
    if proceeding is None:
        return None
    return resync_proceeding(proceeding)


def list_record_subfolders(matter):
    """Sorted names of the matter's Drive subfolders (Notes excluded).

    Fails soft (returns []) when Drive is unlinked, the matter folder is
    missing, or the API errors, so the link modal degrades gracefully.
    """
    if not google.check_credentials() or not matter.drive_folder:
        return []
    try:
        service = google.build_service()
        root_id = google._find_root_folder(service)
        if not root_id:
            return []
        matter_folder = google._find_child_folder(service, root_id, matter.drive_folder)
        if not matter_folder:
            return []
        return sorted(
            child["name"]
            for child in google._list_children(service, matter_folder["id"])
            if child.get("mimeType") == google.FOLDER_MIME
            and child.get("name") != google.NOTES_FOLDER_NAME
        )
    except HttpError:
        logger.exception("Failed to list record subfolders for matter %s", matter.pk)
        return []
