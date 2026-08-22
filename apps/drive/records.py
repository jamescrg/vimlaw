"""Google Drive document mirror: mapped folders -> Documents.

A matter's Drive folder has top-level subfolders mapped to document
categories (and, for Record/Discovery, proceedings) via
``apps.drive.models.DriveFolderMapping`` (the Documents tab's Drive Folder
modal). PDFs anywhere under a mapped folder sync in as ``Document`` rows
with that mapping's category and proceeding: OCR'd, searchable,
highlightable, AI-visible. Unmapped folders are ignored.

Contract:
- Append-only. Drive-side deletions, trashes and moves NEVER remove a
  Document; the record can only shrink through a deliberate in-app delete,
  which tombstones the Drive file id so the file doesn't boomerang back
  (``DriveRecordTombstone``, written by a pre_delete signal).
- PDFs only. Anything else in a mapped folder is counted, not ingested.
- Modified files are refreshed (bytes replaced, OCR reset and re-queued);
  user-set metadata (name, date, description, importance, labels, AI
  settings, highlights) is never touched after the first ingest. Category
  and proceeding follow the mapping only when the file arrives through a
  different mapping than before (moved between mapped folders, or a legacy
  document not yet stamped); within one mapping, hand edits stand.

``apps.drive.google.sync()`` stays the single consumer of the drive-wide
changes feed and dispatches in-scope files here.
"""

import io
import logging
import os
import re
from datetime import datetime

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError
from django.utils import timezone

from apps.case.models import Document

from . import google, mappings
from .models import DriveFolderMapping, DriveRecordTombstone

logger = logging.getLogger(__name__)

PDF_MIME = "application/pdf"

RECORD_STAT_KEYS = (
    "records_synced",
    "records_adopted",
    "records_updated",
    "records_unchanged",
    "records_non_pdf",
    "records_failed",
    "records_unresolved",
)

# The filing convention the upload form also parses (file-upload-forms.js):
# an ISO date prefix names the document's date and is sliced off the name.
_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[\s\-_]*")


def new_record_stats():
    return {key: 0 for key in RECORD_STAT_KEYS}


def is_pdf(file_meta):
    return (
        file_meta.get("mimeType") == PDF_MIME
        or os.path.splitext(file_meta.get("name", ""))[1].lower() == ".pdf"
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


def ingest_mapped(service, file_meta, parts, mapping, dry_run, stats):
    """Upsert one PDF found under a mapped folder."""
    ingest_pdf(service, file_meta, parts, mapping, dry_run, stats)


def ingest_pdf(service, file_meta, parts, mapping, dry_run, stats):
    """Upsert one Drive PDF as a Document (tombstoned ids are skipped).

    ``mapping`` decides matter, category and proceeding. A document that
    already arrived through this same mapping keeps whatever category and
    proceeding it has (hand edits stand); one arriving through a different
    mapping (moved between mapped folders, or never stamped) takes the
    mapping's values, category and proceeding written together so
    Document.save()'s coercion never fights the mapping.
    """
    fid = file_meta["id"]
    mtime = file_meta.get("modifiedTime")
    rel_path = "/".join(parts)[:1024]
    matter = mapping.matter

    if DriveRecordTombstone.objects.filter(drive_file_id=fid).exists():
        return

    existing = Document.objects.filter(drive_file_id=fid).first()

    if existing and existing.drive_modified == mtime:
        # Bytes unchanged; refresh provenance if the file merely moved
        # between mapped folders (or a legacy document gets stamped).
        drifted = existing.drive_mapping_id != mapping.id
        moved = (
            drifted
            or existing.drive_path != rel_path
            or existing.matter_id != matter.id
        )
        if not dry_run and moved:
            fields = {
                "drive_path": rel_path,
                "matter_id": matter.id,
                "drive_synced_at": timezone.now(),
            }
            if drifted:
                fields.update(mappings.apply_mapping_fields(mapping))
            Document.objects.filter(pk=existing.pk).update(**fields)
        stats["records_unchanged"] += 1
        return

    if dry_run:
        stats["records_updated" if existing else "records_synced"] += 1
        return

    name, date = _name_and_date(file_meta)

    if not existing:
        # A manually-uploaded twin (same name, date and size) adopts the
        # Drive identity instead of becoming a duplicate: provenance is
        # attached, bytes and finished OCR stay as they are; category and
        # proceeding follow the folder it was found in.
        candidate = _adopt_candidate(matter, name, date, _meta_size(file_meta))
        if candidate:
            Document.objects.filter(pk=candidate.pk).update(
                drive_file_id=fid,
                drive_path=rel_path,
                drive_modified=mtime,
                drive_synced_at=timezone.now(),
                **mappings.apply_mapping_fields(mapping),
            )
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
        existing.set_fingerprints(io.BytesIO(content), size=len(content))
        _reset_ocr(existing)
        if existing.drive_mapping_id != mapping.id:
            existing.category = mapping.category
            existing.proceeding_id = mapping.proceeding_id
            existing.drive_mapping_id = mapping.id
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
        proceeding_id=mapping.proceeding_id,
        category=mapping.category,
        drive_mapping=mapping,
        name=name,
        date=date,
        drive_file_id=fid,
        drive_path=rel_path,
        drive_modified=mtime,
        drive_synced_at=timezone.now(),
    )
    try:
        document.save()
    except IntegrityError:
        # Another sync pass created this file's row between our lookup and
        # the insert (unique drive_file_id); it will be refreshed next tick.
        stats["records_unchanged"] += 1
        return
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


def mark_missing(mapping, missing):
    """Flag (or clear) a mapping whose Drive folder can't be found."""
    if missing and mapping.missing_since is None:
        mapping.missing_since = timezone.now()
        mapping.save(update_fields=["missing_since", "updated_at"])
    elif not missing and mapping.missing_since is not None:
        mapping.missing_since = None
        mapping.save(update_fields=["missing_since", "updated_at"])


def resync_mapping(mapping):
    """Ingest one mapped folder now (mapping created or changed).

    Never deletes anything: unmapping a folder, or a folder that no longer
    exists, leaves already-synced Documents in place. Returns a stats dict
    (with ``missing: True`` when the folder wasn't found), or None when
    Drive or the matter link isn't set up.
    """
    matter = mapping.matter
    if not google.check_credentials():
        return None
    if matter is None or not (matter.drive_folder or matter.drive_folder_id):
        return None

    service = google.build_service()
    root_id = google._find_root_folder(service)
    if not root_id:
        return None

    stats = new_record_stats()
    matter_folder = google.find_matter_folder(service, root_id, matter)
    folder = (
        google.resolve_mapping_folder(service, matter_folder["id"], mapping)
        if matter_folder
        else None
    )
    if folder is None:
        logger.warning(
            "Mapped folder %r not found for matter %s", mapping.folder_path, matter.pk
        )
        mark_missing(mapping, True)
        return {**stats, "missing": True}

    mark_missing(mapping, False)
    prefix = [matter_folder["name"]] + mapping.folder_path.split("/")
    others = set(
        DriveFolderMapping.objects.filter(matter=matter)
        .exclude(pk=mapping.pk)
        .exclude(folder_id__isnull=True)
        .values_list("folder_id", flat=True)
    )
    google._walk_mapped_folder(
        service, folder, prefix, mapping, False, stats, skip=others
    )
    return stats


def resync_mapping_by_id(mapping_id):
    """async_task entry point for the Drive Folder modal."""
    mapping = (
        DriveFolderMapping.objects.filter(pk=mapping_id)
        .select_related("matter", "proceeding")
        .first()
    )
    if mapping is None:
        return None
    return resync_mapping(mapping)
