"""Google Drive case-notes mirror.

Pulls case notes from Google Drive into the database as ``Note`` rows, scoped to
the ``Notes`` subfolder of each matter under a configured root folder (default
``Matters - Open``). Reuses the project's existing Google OAuth plumbing
(see apps/calendar/google.py) and the Drive Changes API for incremental,
near-real-time sync.

Storage model (DB-canonical):
- The converted Markdown text lives in ``Note.content`` (Postgres), so the AI
  context builder and the in-app Notes UI read it directly — no file tree of
  record. A synced note carries provenance (``drive_file_id``, ``drive_path``,
  ``drive_modified``, ``drive_synced_at``) and is upserted by ``drive_file_id``.
- An optional debug mirror (settings.DRIVE_NOTES_DEBUG_DIR, off by default)
  additionally writes the Markdown to disk for inspection.

Flow:
- bootstrap(): first run (no saved page token) crawls every
  ``<root>/<matter>/Notes/**`` file, converts it, and upserts a Note, then
  stores a Changes API start page token.
- sync(): on each tick, consume the changes delta since the saved token,
  filtering to in-scope note files, and upsert/delete accordingly.

The Changes API is drive-wide, so each changed file is resolved by walking its
parent chain up to the root folder; only files whose path is
``<root>/<matter>/Notes/...`` with an allowed extension are mirrored. A note's
matter is resolved via ``Matter.drive_folder`` (set by the link_drive_folders
command); folders with no matching Matter are recorded as unmatched.

This module owns the single changes-feed cursor and also dispatches to the
record-folder mirror (apps/drive/records.py): PDFs under
``<root>/<matter>/<linked record folder>/...`` become Record Documents on
the linked proceeding. That mirror is append-only — removals and trashes
only ever affect Notes here.
"""

import json
import logging
import os
from io import BytesIO

import google.oauth2.credentials
from django.conf import settings
from django.utils import timezone
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from apps.matters.models import Matter
from apps.notes.models import Note
from utils.prepare_path import prepare_path

from . import convert, records
from .models import DriveSyncState

logger = logging.getLogger(__name__)

DRIVE_TOKEN_PATH = "google/drive_tokens.json"

FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
GOOGLE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

ALLOWED_EXTENSIONS = (".docx", ".odt", ".md", ".xlsx", ".ods", ".csv")
NOTES_FOLDER_NAME = "Notes"

# Fields requested for a file in changes/listing responses. createdTime and
# size feed the record mirror (fallback date; duplicate-adoption check).
FILE_FIELDS = "id, name, mimeType, parents, trashed, modifiedTime, createdTime, size"


# --------------------------------------------------------------------------- #
# Auth (mirrors apps/calendar/google.py)
# --------------------------------------------------------------------------- #
def check_credentials():
    """Return True if a Drive account is linked (token file holds a token)."""
    prepare_path(DRIVE_TOKEN_PATH)
    try:
        with open(DRIVE_TOKEN_PATH, "r") as f:
            credentials = f.read()
    except FileNotFoundError:
        return False
    return "token" in credentials


def build_service():
    """Build an authenticated Drive v3 service, or False if not linked."""
    prepare_path(DRIVE_TOKEN_PATH)

    with open(DRIVE_TOKEN_PATH, "r") as f:
        token = f.read()

    if not token:
        return False

    credentials = google.oauth2.credentials.Credentials.from_authorized_user_info(
        json.loads(token)
    )
    return build("drive", "v3", credentials=credentials)


# --------------------------------------------------------------------------- #
# Shared-drive aware request params
# --------------------------------------------------------------------------- #
def _list_args():
    """Params for files().list — supports an optional Shared Drive."""
    args = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}
    if settings.DRIVE_SHARED_DRIVE_ID:
        args.update(
            {
                "corpora": "drive",
                "driveId": settings.DRIVE_SHARED_DRIVE_ID,
                "spaces": "drive",
            }
        )
    return args


def _changes_args():
    """Params for changes().list (accepts includeItemsFromAllDrives)."""
    args = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}
    if settings.DRIVE_SHARED_DRIVE_ID:
        args["driveId"] = settings.DRIVE_SHARED_DRIVE_ID
    return args


def _page_token_args():
    """Params for changes().getStartPageToken.

    getStartPageToken does NOT accept includeItemsFromAllDrives — only
    supportsAllDrives (and driveId for a Shared Drive).
    """
    args = {"supportsAllDrives": True}
    if settings.DRIVE_SHARED_DRIVE_ID:
        args["driveId"] = settings.DRIVE_SHARED_DRIVE_ID
    return args


# --------------------------------------------------------------------------- #
# Folder / path resolution
# --------------------------------------------------------------------------- #
def _find_root_folder(service):
    """Return the Drive folderId of the notes root, or None if not found."""
    name = settings.DRIVE_NOTES_ROOT.replace("'", "\\'")
    q = f"name = '{name}' and mimeType = '{FOLDER_MIME}' and trashed = false"
    resp = service.files().list(q=q, fields="files(id, name)", **_list_args()).execute()
    files = resp.get("files", [])
    return files[0]["id"] if files else None


def _list_children(service, parent_id):
    """Yield all non-trashed children (files and folders) of a folder."""
    page_token = None
    q = f"'{parent_id}' in parents and trashed = false"
    while True:
        resp = (
            service.files()
            .list(
                q=q,
                fields=f"nextPageToken, files({FILE_FIELDS})",
                pageToken=page_token,
                pageSize=1000,
                **_list_args(),
            )
            .execute()
        )
        for child in resp.get("files", []):
            yield child
        page_token = resp.get("nextPageToken")
        if not page_token:
            break


def _walk_to_root(service, file_meta, root_id, folder_cache):
    """Walk a file's parent chain up to root_id.

    Returns the list of path parts from just under the root down to the file
    (e.g. ["Smith v. Jones", "Notes", "intake.docx"]), or None if the root is
    not an ancestor.
    """
    parts = [file_meta["name"]]
    parents = file_meta.get("parents") or []
    current = parents[0] if parents else None

    guard = 0
    while current and guard < 50:
        guard += 1
        if current == root_id:
            return parts
        if current not in folder_cache:
            try:
                meta = (
                    service.files()
                    .get(
                        fileId=current,
                        fields="id, name, parents",
                        supportsAllDrives=True,
                    )
                    .execute()
                )
            except HttpError:
                return None
            folder_cache[current] = meta
        folder = folder_cache[current]
        parts.insert(0, folder.get("name", ""))
        fparents = folder.get("parents") or []
        current = fparents[0] if fparents else None

    return None


def _in_notes_scope(parts):
    """True if path parts are <matter>/Notes/... (a note file in scope)."""
    return bool(parts) and len(parts) >= 3 and parts[1] == NOTES_FOLDER_NAME


def _effective_ext(file_meta):
    """Return the source extension to convert from.

    Google-native files are exported: Docs -> .docx, Sheets -> .xlsx (XLSX
    preserves every tab, whereas a CSV export would only yield the first sheet).
    """
    mime = file_meta.get("mimeType")
    if mime == GOOGLE_DOC_MIME:
        return ".docx"
    if mime == GOOGLE_SHEET_MIME:
        return ".xlsx"
    return os.path.splitext(file_meta.get("name", ""))[1].lower()


def _is_allowed(file_meta):
    """True if the file is a convertible note (by extension or Google native)."""
    if file_meta.get("mimeType") in (GOOGLE_DOC_MIME, GOOGLE_SHEET_MIME):
        return True
    return os.path.splitext(file_meta.get("name", ""))[1].lower() in ALLOWED_EXTENSIONS


def _matters_by_folder():
    """Map Matter.drive_folder -> Matter for all linked matters."""
    qs = Matter.objects.exclude(drive_folder__isnull=True).exclude(drive_folder="")
    return {m.drive_folder: m for m in qs}


# --------------------------------------------------------------------------- #
# Optional debug mirror (off unless settings.DRIVE_NOTES_DEBUG_DIR is set)
# --------------------------------------------------------------------------- #
def _debug_path(debug_dir, rel_path):
    return os.path.join(debug_dir, os.path.splitext(rel_path)[0] + ".md")


def _write_debug(debug_dir, rel_path, markdown):
    out = _debug_path(debug_dir, rel_path)
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(markdown)
    except OSError as e:
        logger.warning("Debug mirror write failed for %s: %s", rel_path, e)


def _delete_debug(debug_dir, rel_path):
    try:
        out = _debug_path(debug_dir, rel_path)
        if os.path.exists(out):
            os.remove(out)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #
def _download(service, file_meta):
    """Download a file's bytes (exporting Google Docs to .docx)."""
    file_id = file_meta["id"]
    mime = file_meta.get("mimeType")
    if mime == GOOGLE_DOC_MIME:
        request = service.files().export_media(fileId=file_id, mimeType=DOCX_MIME)
    elif mime == GOOGLE_SHEET_MIME:
        request = service.files().export_media(fileId=file_id, mimeType=XLSX_MIME)
    else:
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)

    buf = BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Upsert / remove a single note
# --------------------------------------------------------------------------- #
def _ingest(service, file_meta, parts, matters, debug_dir, dry_run, stats, unmatched):
    """Convert one note file and upsert its Note row."""
    matter = matters.get(parts[0])
    if matter is None:
        unmatched.add(parts[0])
        return

    fid = file_meta["id"]
    mtime = file_meta.get("modifiedTime")
    rel_path = "/".join(parts)
    title = os.path.splitext(file_meta["name"])[0]

    existing = Note.objects.filter(drive_file_id=fid).first()
    if existing and existing.drive_modified == mtime:
        # Content unchanged; refresh path/matter if the file merely moved.
        if not dry_run and (
            existing.drive_path != rel_path or existing.matter_id != matter.id
        ):
            existing.drive_path = rel_path
            existing.matter = matter
            existing.drive_synced_at = timezone.now()
            existing.save(update_fields=["drive_path", "matter", "drive_synced_at"])
        stats["skipped"] += 1
        return

    if dry_run:
        stats["would-convert"] += 1
        return

    content = _download(service, file_meta)
    markdown = convert.to_markdown(content, _effective_ext(file_meta))

    Note.objects.update_or_create(
        drive_file_id=fid,
        defaults={
            "matter": matter,
            "title": title,
            "content": markdown,
            "drive_path": rel_path,
            "drive_modified": mtime,
            "drive_synced_at": timezone.now(),
        },
    )
    if debug_dir:
        _write_debug(debug_dir, rel_path, markdown)
    stats["converted"] += 1


def _remove_note(file_id, debug_dir, dry_run, stats):
    """Delete the Note (and debug file) for a removed/out-of-scope Drive file."""
    note = Note.objects.filter(drive_file_id=file_id).first()
    if not note:
        return
    if not dry_run:
        if debug_dir and note.drive_path:
            _delete_debug(debug_dir, note.drive_path)
        note.delete()
    stats["removed"] += 1


# --------------------------------------------------------------------------- #
# Bootstrap (full crawl) + incremental sync
# --------------------------------------------------------------------------- #
def _new_stats():
    return {
        "converted": 0,
        "skipped": 0,
        "removed": 0,
        "would-convert": 0,
        "failed": 0,
    } | records.new_record_stats()


def _walk_record_folder(service, record_folder, prefix, links, dry_run, stats):
    """DFS one linked record folder, ingesting PDFs (append-only mirror)."""
    stack = [(record_folder["id"], prefix)]
    while stack:
        folder_id, path = stack.pop()
        for child in _list_children(service, folder_id):
            if child.get("mimeType") == FOLDER_MIME:
                stack.append((child["id"], path + [child["name"]]))
                continue
            if not records.is_pdf(child):
                stats["records_non_pdf"] += 1
                continue
            try:
                records.ingest_record(
                    service, child, path + [child["name"]], links, dry_run, stats
                )
            except Exception:
                stats["records_failed"] += 1
                logger.exception("Failed to sync record %s", child.get("name"))


def bootstrap(service, root_id, matters, links, debug_dir, dry_run=False):
    """Crawl every <root>/<matter>/Notes/** file and upsert Note rows, and
    every linked record folder's PDFs into Record Documents.

    Reconciles NOTE deletions: any synced Note whose Drive file is no longer
    present is removed. Record Documents are never reconciled away — that
    mirror is append-only. Returns (stats, unmatched_folder_names,
    missing_record_folders).
    """
    stats = _new_stats()
    unmatched = set()
    missing_records = set()
    seen = set()

    for matter_folder in _list_children(service, root_id):
        if matter_folder.get("mimeType") != FOLDER_MIME:
            continue
        if matter_folder["name"] not in matters:
            unmatched.add(matter_folder["name"])
            continue

        children = [
            c
            for c in _list_children(service, matter_folder["id"])
            if c.get("mimeType") == FOLDER_MIME
        ]
        notes_folder = next(
            (c for c in children if c.get("name") == NOTES_FOLDER_NAME), None
        )

        if notes_folder:
            stack = [(notes_folder["id"], [matter_folder["name"], NOTES_FOLDER_NAME])]
            while stack:
                folder_id, prefix = stack.pop()
                for child in _list_children(service, folder_id):
                    if child.get("mimeType") == FOLDER_MIME:
                        stack.append((child["id"], prefix + [child["name"]]))
                        continue
                    if not _is_allowed(child):
                        continue
                    # Mark seen before converting so a conversion failure
                    # doesn't delete a previously-synced note as "stale".
                    seen.add(child["id"])
                    try:
                        _ingest(
                            service,
                            child,
                            prefix + [child["name"]],
                            matters,
                            debug_dir,
                            dry_run,
                            stats,
                            unmatched,
                        )
                    except Exception:
                        stats["failed"] += 1
                        logger.exception("Failed to sync note %s", child.get("name"))

        # Linked record folders for this matter.
        for (m_folder, r_folder), _proceeding in links.items():
            if m_folder != matter_folder["name"]:
                continue
            record_folder = next(
                (c for c in children if c.get("name") == r_folder), None
            )
            if record_folder is None:
                missing_records.add(f"{m_folder}/{r_folder}")
                continue
            _walk_record_folder(
                service,
                record_folder,
                [m_folder, r_folder],
                links,
                dry_run,
                stats,
            )

    # Any synced Note not seen in the crawl is stale. (Notes only — record
    # Documents are append-only by contract.)
    stale = Note.objects.filter(drive_file_id__isnull=False).exclude(
        drive_file_id__in=seen
    )
    for note in stale:
        if not dry_run:
            if debug_dir and note.drive_path:
                _delete_debug(debug_dir, note.drive_path)
            note.delete()
        stats["removed"] += 1

    return stats, unmatched, missing_records


def _process_change(
    service,
    change,
    root_id,
    matters,
    links,
    folder_cache,
    debug_dir,
    dry_run,
    stats,
    unmatched,
):
    file_id = change.get("fileId")
    file_meta = change.get("file")

    # Removal / trash: we only get a fileId, so use our bookkeeping to delete.
    # Notes only — the record mirror is append-only, so a removed record PDF
    # leaves its Document (and OCR/highlights) untouched.
    if change.get("removed") or (file_meta and file_meta.get("trashed")):
        _remove_note(file_id, debug_dir, dry_run, stats)
        return

    if not file_meta or file_meta.get("mimeType") == FOLDER_MIME:
        # Folder renames/moves are reconciled by the periodic --full sync.
        return

    parts = _walk_to_root(service, file_meta, root_id, folder_cache)

    if _in_notes_scope(parts):
        if not _is_allowed(file_meta):
            # A note replaced by a disallowed type stops being a note.
            _remove_note(file_id, debug_dir, dry_run, stats)
            return
        try:
            _ingest(
                service, file_meta, parts, matters, debug_dir, dry_run, stats, unmatched
            )
        except Exception:
            stats["failed"] += 1
            logger.exception("Failed to sync note %s", file_meta.get("name"))
        return

    if records.in_record_scope(parts, links):
        if not records.is_pdf(file_meta):
            stats["records_non_pdf"] += 1
            return
        try:
            records.ingest_record(service, file_meta, parts, links, dry_run, stats)
        except Exception:
            stats["records_failed"] += 1
            logger.exception("Failed to sync record %s", file_meta.get("name"))
        return

    # Out of every scope; clean up a note we may have been tracking (a
    # record Document, by contract, stays).
    _remove_note(file_id, debug_dir, dry_run, stats)


def sync(dry_run=False, full=False, debug_dir=None):
    """Entry point for the sync. No-ops when no Drive account is linked.

    Returns a stats dict (with an ``unmatched`` list), or None when skipped.
    """
    if not check_credentials():
        logger.info("Google Drive not linked; skipping case-notes sync.")
        return None

    service = build_service()
    root_id = _find_root_folder(service)
    if not root_id:
        logger.warning(
            "Drive notes root folder %r not found.", settings.DRIVE_NOTES_ROOT
        )
        return None

    if debug_dir is None:
        debug_dir = settings.DRIVE_NOTES_DEBUG_DIR or ""
    matters = _matters_by_folder()
    links = records.proceedings_by_folder()
    state, _ = DriveSyncState.objects.get_or_create(pk=1)

    # First run or forced full: crawl everything, then capture a start token.
    if full or not state.page_token:
        stats, unmatched, missing_records = bootstrap(
            service, root_id, matters, links, debug_dir, dry_run
        )
        token = service.changes().getStartPageToken(**_page_token_args()).execute()
        if not dry_run:
            state.page_token = token["startPageToken"]
            state.unmatched_folders = sorted(unmatched)
            state.missing_record_folders = sorted(missing_records)
            state.save()
        logger.info(
            "Drive notes bootstrap complete: %s (unmatched: %s, missing record "
            "folders: %s)",
            stats,
            sorted(unmatched),
            sorted(missing_records),
        )
        return {
            **stats,
            "unmatched": sorted(unmatched),
            "missing_record_folders": sorted(missing_records),
        }

    # Incremental: consume the changes delta.
    stats = _new_stats()
    unmatched = set(state.unmatched_folders or [])
    folder_cache = {}
    page_token = state.page_token
    try:
        while page_token:
            resp = (
                service.changes()
                .list(
                    pageToken=page_token,
                    includeRemoved=True,
                    fields=(
                        "newStartPageToken, nextPageToken, "
                        f"changes(fileId, removed, file({FILE_FIELDS}))"
                    ),
                    pageSize=1000,
                    **_changes_args(),
                )
                .execute()
            )
            for change in resp.get("changes", []):
                _process_change(
                    service,
                    change,
                    root_id,
                    matters,
                    links,
                    folder_cache,
                    debug_dir,
                    dry_run,
                    stats,
                    unmatched,
                )

            if "nextPageToken" in resp:
                page_token = resp["nextPageToken"]
            else:
                if not dry_run:
                    state.page_token = resp["newStartPageToken"]
                    state.unmatched_folders = sorted(unmatched)
                    state.save()
                page_token = None
    except HttpError as e:
        # 410 Gone => the page token expired; clear it and re-bootstrap.
        if e.resp.status == 410:
            logger.warning("Drive page token expired; re-bootstrapping.")
            state.page_token = None
            if not dry_run:
                state.save()
            return sync(dry_run=dry_run, full=True, debug_dir=debug_dir)
        raise

    logger.info("Drive notes sync complete: %s", stats)
    return {**stats, "unmatched": sorted(unmatched)}


def get_sync_status():
    """Summary for the Settings > Integrations health panel (DB-only)."""
    from apps.case.models import Document

    linked_matters = (
        Matter.objects.exclude(drive_folder__isnull=True)
        .exclude(drive_folder="")
        .count()
    )
    state = DriveSyncState.objects.first()
    return {
        "linked": check_credentials(),
        "synced_count": Note.objects.filter(drive_file_id__isnull=False).count(),
        "linked_matters": linked_matters,
        "synced_records": Document.objects.filter(drive_file_id__isnull=False).count(),
        "linked_proceedings": len(records.proceedings_by_folder()),
        "missing_record_folders": state.missing_record_folders if state else [],
    }


# --------------------------------------------------------------------------- #
# Per-matter folder linking (used by the Notes-tab "Link Drive Folder" UI)
# --------------------------------------------------------------------------- #
def _find_child_folder(service, parent_id, name):
    """Return the child folder with the given name, or None."""
    for child in _list_children(service, parent_id):
        if child.get("mimeType") == FOLDER_MIME and child.get("name") == name:
            return child
    return None


def list_matter_folders():
    """Return sorted folder names directly under the notes root.

    Fails soft (returns []) if Drive is unlinked, the root is missing, or the
    Drive API errors (e.g. API not enabled / transient) so the picker modal
    degrades to an empty list instead of a 500.
    """
    if not check_credentials():
        return []
    try:
        service = build_service()
        root_id = _find_root_folder(service)
        if not root_id:
            return []
        return sorted(
            child["name"]
            for child in _list_children(service, root_id)
            if child.get("mimeType") == FOLDER_MIME
        )
    except HttpError:
        logger.exception("Failed to list Drive matter folders")
        return []


def _delete_synced_for_matter(matter, debug_dir, keep_ids, stats):
    """Delete this matter's synced notes whose Drive file is not in keep_ids."""
    qs = Note.objects.filter(matter=matter, drive_file_id__isnull=False).exclude(
        drive_file_id__in=keep_ids
    )
    for note in qs:
        if debug_dir and note.drive_path:
            _delete_debug(debug_dir, note.drive_path)
        note.delete()
        stats["removed"] += 1


def resync_matter(matter, debug_dir=None):
    """Re-sync just one matter's notes from its linked Drive folder.

    Used when a user links/changes a matter's Drive folder in the UI: ingests
    the folder's Notes/** files and removes this matter's synced notes that are
    no longer present (e.g. after re-linking to a different folder). If the
    matter is unlinked, simply drops its synced notes. No-op when Drive is not
    linked. Resilient to per-file conversion failures. Returns a stats dict.
    """
    if not check_credentials():
        return None
    if debug_dir is None:
        debug_dir = settings.DRIVE_NOTES_DEBUG_DIR or ""

    stats = _new_stats()

    if not matter.drive_folder:
        _delete_synced_for_matter(matter, debug_dir, set(), stats)
        return stats

    service = build_service()
    root_id = _find_root_folder(service)
    if not root_id:
        return None

    matters = {matter.drive_folder: matter}
    seen = set()
    unmatched = set()

    matter_folder = _find_child_folder(service, root_id, matter.drive_folder)
    notes_folder = (
        _find_child_folder(service, matter_folder["id"], NOTES_FOLDER_NAME)
        if matter_folder
        else None
    )
    if notes_folder:
        stack = [(notes_folder["id"], [matter.drive_folder, NOTES_FOLDER_NAME])]
        while stack:
            folder_id, prefix = stack.pop()
            for child in _list_children(service, folder_id):
                if child.get("mimeType") == FOLDER_MIME:
                    stack.append((child["id"], prefix + [child["name"]]))
                    continue
                if not _is_allowed(child):
                    continue
                # Mark seen before converting so a conversion failure doesn't
                # delete a previously-synced note as "stale".
                seen.add(child["id"])
                try:
                    _ingest(
                        service,
                        child,
                        prefix + [child["name"]],
                        matters,
                        debug_dir,
                        False,
                        stats,
                        unmatched,
                    )
                except Exception:
                    stats["failed"] += 1
                    logger.exception(
                        "Failed to sync note %s for matter %s",
                        child.get("name"),
                        matter.pk,
                    )

    # Drop this matter's synced notes that are no longer in the folder.
    _delete_synced_for_matter(matter, debug_dir, seen, stats)
    return stats
