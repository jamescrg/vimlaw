"""Google Drive document mirrors (changes-feed owner).

Owns the single Drive Changes API cursor and dispatches to the document
mirrors (apps/drive/records.py): PDFs under
``<root>/<matter>/<linked record folder>/...`` become Record Documents on
the linked proceeding, and PDFs under any convention-named "Key Documents"
folder become Evidence documents (curation by drag). Both mirrors are
append-only — removals and trashes in Drive never delete app rows.

Reuses the project's existing Google OAuth plumbing (see
apps/calendar/google.py). A matter is resolved via ``Matter.drive_folder``
(set by the link_drive_folders command or the notes-tab link modal);
folders with no matching Matter are recorded as unmatched.

Flow:
- bootstrap(): first run (no saved page token) crawls the linked record
  folders and Key Documents folders, then stores a Changes API start token.
- sync(): on each tick, consume the changes delta since the saved token.

RETIRED (2026-08-11): the case-notes mirror. This module used to pull
``<root>/<matter>/Notes/**`` files into ``Note`` rows and delete them when
the Drive file vanished. Notes are app-owned now — previously synced notes
keep their provenance fields (``drive_file_id``, ``drive_path``,
``drive_modified``, ``drive_synced_at``) and are editable in the app; files
under ``Notes/`` are ignored by the sync.
"""

import json
import logging
from io import BytesIO

import google.oauth2.credentials
from django.conf import settings
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from apps.matters.models import Matter
from apps.notes.models import Note
from utils.prepare_path import prepare_path

from . import records
from .models import DriveSyncState

logger = logging.getLogger(__name__)

DRIVE_TOKEN_PATH = settings.GOOGLE_DRIVE_TOKEN_PATH

FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
GOOGLE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# The retired notes mirror's subtree; still skipped by the Key Documents
# folder search.
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


def _matters_by_folder():
    """Map Matter.drive_folder -> Matter for all linked matters."""
    qs = Matter.objects.exclude(drive_folder__isnull=True).exclude(drive_folder="")
    return {m.drive_folder: m for m in qs}


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
# Bootstrap (full crawl) + incremental sync
# --------------------------------------------------------------------------- #
def _new_stats():
    return records.new_record_stats()


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


def _walk_key_folder(service, key_folder, prefix, matter, dry_run, stats):
    """DFS one Key Documents folder, ingesting PDFs as Evidence."""
    stack = [(key_folder["id"], prefix)]
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
                records.ingest_pdf(
                    service,
                    child,
                    path + [child["name"]],
                    matter,
                    None,
                    "Evidence",
                    dry_run,
                    stats,
                )
            except Exception:
                stats["records_failed"] += 1
                logger.exception("Failed to sync key document %s", child.get("name"))


def _find_key_folders(service, matter_folder, children, links):
    """Locate Key Documents folders anywhere inside a matter's folder.

    Walks the folder tree only (never lists files outside the targets),
    skipping the Notes subtree and linked record folders, which keep their
    own semantics. Returns [(folder_meta, path_prefix_parts)].
    """
    key_name = records.key_folder_name()
    if not key_name:
        return []
    matter_name = matter_folder["name"]
    found = []
    stack = [(child, [matter_name]) for child in children]
    while stack:
        folder, prefix = stack.pop()
        name = folder.get("name")
        if len(prefix) == 1 and name == NOTES_FOLDER_NAME:
            continue
        if (matter_name, name) in links and len(prefix) == 1:
            continue
        if name == key_name:
            found.append((folder, prefix + [name]))
            continue  # nested Key folders inside Key are just subfolders
        for sub in _list_children(service, folder["id"]):
            if sub.get("mimeType") == FOLDER_MIME:
                stack.append((sub, prefix + [name]))
    return found


def bootstrap(service, root_id, matters, links, dry_run=False):
    """Crawl every linked record folder's PDFs into Record Documents, and
    every Key Documents folder's PDFs into Evidence.

    Both mirrors are append-only; nothing is ever reconciled away. Returns
    (stats, unmatched_folder_names, missing_record_folders).
    """
    stats = _new_stats()
    unmatched = set()
    missing_records = set()

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

        # Key Documents folders (convention-named curated evidence).
        matter = matters[matter_folder["name"]]
        for key_folder, prefix in _find_key_folders(
            service, matter_folder, children, links
        ):
            _walk_key_folder(service, key_folder, prefix, matter, dry_run, stats)

    return stats, unmatched, missing_records


def _process_change(
    service,
    change,
    root_id,
    matters,
    links,
    folder_cache,
    dry_run,
    stats,
    unmatched,
):
    file_meta = change.get("file")

    # Removal / trash: both mirrors are append-only, so a removed or trashed
    # Drive file leaves its app rows (documents, notes) untouched.
    if change.get("removed") or (file_meta and file_meta.get("trashed")):
        return

    if not file_meta or file_meta.get("mimeType") == FOLDER_MIME:
        # Folder renames/moves are reconciled by the periodic --full sync.
        return

    parts = _walk_to_root(service, file_meta, root_id, folder_cache)

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

    if records.in_key_scope(parts, matters):
        if not records.is_pdf(file_meta):
            stats["records_non_pdf"] += 1
            return
        try:
            records.ingest_pdf(
                service,
                file_meta,
                parts,
                matters[parts[0]],
                None,
                "Evidence",
                dry_run,
                stats,
            )
        except Exception:
            stats["records_failed"] += 1
            logger.exception("Failed to sync key document %s", file_meta.get("name"))
        return

    # Out of every scope: nothing to do (dragging a file out of a mirrored
    # folder leaves its app rows in place — both mirrors are append-only).


def sync(dry_run=False, full=False):
    """Entry point for the sync. No-ops when no Drive account is linked.

    Returns a stats dict (with an ``unmatched`` list), or None when skipped.
    """
    if not check_credentials():
        logger.info("Google Drive not linked; skipping Drive sync.")
        return None

    service = build_service()
    root_id = _find_root_folder(service)
    if not root_id:
        logger.warning("Drive root folder %r not found.", settings.DRIVE_NOTES_ROOT)
        return None

    matters = _matters_by_folder()
    links = records.proceedings_by_folder()
    state, _ = DriveSyncState.objects.get_or_create(pk=1)

    # First run or forced full: crawl everything, then capture a start token.
    if full or not state.page_token:
        stats, unmatched, missing_records = bootstrap(
            service, root_id, matters, links, dry_run
        )
        token = service.changes().getStartPageToken(**_page_token_args()).execute()
        if not dry_run:
            state.page_token = token["startPageToken"]
            state.unmatched_folders = sorted(unmatched)
            state.missing_record_folders = sorted(missing_records)
            state.save()
        logger.info(
            "Drive bootstrap complete: %s (unmatched: %s, missing record folders: %s)",
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
            return sync(dry_run=dry_run, full=True)
        raise

    logger.info("Drive sync complete: %s", stats)
    return {**stats, "unmatched": sorted(unmatched)}


def scheduled_sync():
    return sync()


def scheduled_sync_full():
    return sync(full=True)


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
    """Return the child folder with the given name, or None (records resync)."""
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
