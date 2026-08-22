"""Google Drive document mirror (changes-feed owner).

Owns the single Drive Changes API cursor and dispatches to the document
mirror (apps/drive/records.py): a matter's Drive folder has top-level
subfolders mapped to document categories and proceedings
(apps.drive.models.DriveFolderMapping, set in the Documents tab's Drive
Folder modal), and PDFs anywhere under a mapped folder become Documents
with that mapping's category and proceeding. The mirror is append-only —
removals and trashes in Drive never delete app rows.

Reuses the project's existing Google OAuth plumbing (see
apps/calendar/google.py). A matter is resolved by ``Matter.drive_folder_id``
(falling back to the folder name in ``Matter.drive_folder`` for links made
before ids were stored, which are then upgraded in place); root-level
folders with no matching Matter are recorded as unmatched.

Flow:
- bootstrap(): first run (no saved page token) or the nightly full pass
  crawls every mapped folder, refreshes cached names, flags missing
  folders, records each matter's unmapped subfolders for the Documents-tab
  badge, then stores a Changes API start token.
- sync(): on each tick, consume the changes delta since the saved token.

RETIRED: the case-notes mirror (2026-08-11; files under ``Notes/`` are
ignored) and the zero-config "Key Documents" convention (2026-08-21;
legacy nested rows such as ``Evidence/Key Documents`` were converted into
mappings and keep syncing until unmapped).
"""

import json
import logging
from io import BytesIO

import google.oauth2.credentials
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from apps.matters.models import Matter
from utils.prepare_path import prepare_path

from . import (
    mappings as mapping_rules,
    records,
)
from .models import DriveFolderMapping, DriveMatterState, DriveSyncState

logger = logging.getLogger(__name__)

DRIVE_TOKEN_PATH = settings.GOOGLE_DRIVE_TOKEN_PATH

FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
GOOGLE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# The retired notes mirror's subtree; excluded from the mapping table and
# the unmapped-folder nudge.
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

    Returns the chain [(folder_id, name), ...] from just under the root down
    to the file itself (e.g. [("mf1", "Smith v. Jones"), ("rf1", "Record"),
    ("f1", "Complaint.pdf")]), or None if the root is not an ancestor, an
    ancestor is trashed, or the chain can't be resolved.
    """
    chain = [(file_meta["id"], file_meta["name"])]
    parents = file_meta.get("parents") or []
    current = parents[0] if parents else None

    guard = 0
    while current and guard < 50:
        guard += 1
        if current == root_id:
            return chain
        if current not in folder_cache:
            try:
                meta = (
                    service.files()
                    .get(
                        fileId=current,
                        fields="id, name, parents, trashed",
                        supportsAllDrives=True,
                    )
                    .execute()
                )
            except HttpError:
                return None
            folder_cache[current] = meta
        folder = folder_cache[current]
        if folder.get("trashed"):
            return None
        chain.insert(0, (folder.get("id", current), folder.get("name", "")))
        fparents = folder.get("parents") or []
        current = fparents[0] if fparents else None

    return None


def _linked_matters():
    """Matters linked to a Drive folder (by id, or by name for old links)."""
    return Matter.objects.filter(
        Q(drive_folder_id__isnull=False)
        | (Q(drive_folder__isnull=False) & ~Q(drive_folder=""))
    )


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


def _walk_mapped_folder(service, folder, prefix, mapping, dry_run, stats, skip=()):
    """DFS one mapped folder, ingesting PDFs (append-only mirror).

    ``prefix`` is the path parts down to and including this folder (matter
    folder first); nested subfolders inherit the mapping, except folders in
    ``skip`` (the matter's other mapped folder ids, e.g. a legacy nested
    row), which their own mapping walks.
    """
    stack = [(folder["id"], list(prefix))]
    while stack:
        folder_id, path = stack.pop()
        for child in _list_children(service, folder_id):
            if child.get("mimeType") == FOLDER_MIME:
                if child["id"] in skip:
                    continue
                stack.append((child["id"], path + [child["name"]]))
                continue
            if not records.is_pdf(child):
                stats["records_non_pdf"] += 1
                continue
            try:
                records.ingest_mapped(
                    service, child, path + [child["name"]], mapping, dry_run, stats
                )
            except Exception:
                stats["records_failed"] += 1
                logger.exception("Failed to sync %s", child.get("name"))


def _refresh_mapping_path(mapping, live_name):
    """Keep the cached path's last segment equal to the live folder name."""
    head, _, _tail = mapping.folder_path.rpartition("/")
    path = f"{head}/{live_name}" if head else live_name
    if path != mapping.folder_path:
        mapping.folder_path = path[:1024]
        mapping.save(update_fields=["folder_path", "updated_at"])


def _bootstrap_matter(service, matter_folder, matter, dry_run, stats):
    """Crawl one linked matter: resolve its mappings, ingest, record state."""
    top = list_child_folders(service, matter_folder["id"])
    top_by_id = {f["id"]: f for f in top}
    live_name = matter_folder["name"]

    if not dry_run and (
        matter.drive_folder_id != matter_folder["id"]
        or matter.drive_folder != live_name
    ):
        # Upgrade a name-only link to the id, and follow a rename in Drive.
        Matter.objects.filter(pk=matter.pk).update(
            drive_folder_id=matter_folder["id"], drive_folder=live_name
        )
        matter.drive_folder_id = matter_folder["id"]
        matter.drive_folder = live_name

    # Resolve every mapping's folder first (legacy path rows get their id),
    # so each walk can skip the folders the matter's other mappings own.
    resolved = []
    for mapping in DriveFolderMapping.objects.filter(matter=matter).select_related(
        "matter", "proceeding"
    ):
        if mapping.folder_id:
            folder = top_by_id.get(mapping.folder_id) or get_folder(
                service, mapping.folder_id
            )
        else:
            folder = _resolve_path(service, matter_folder["id"], mapping.folder_path)
            if folder is not None and not dry_run:
                mapping.folder_id = folder["id"]
                mapping.save(update_fields=["folder_id", "updated_at"])
        if folder is None:
            if not dry_run:
                records.mark_missing(mapping, True)
            continue
        if not dry_run:
            records.mark_missing(mapping, False)
            _refresh_mapping_path(mapping, folder["name"])
        resolved.append((mapping, folder))

    mapped_ids = {folder["id"] for _, folder in resolved}
    for mapping, folder in resolved:
        prefix = [live_name] + mapping.folder_path.split("/")
        _walk_mapped_folder(
            service,
            folder,
            prefix,
            mapping,
            dry_run,
            stats,
            skip=mapped_ids - {folder["id"]},
        )

    if not dry_run:
        mapping_rules.record_matter_state(
            matter, [f for f in top if f["name"] != NOTES_FOLDER_NAME]
        )


def bootstrap(service, root_id, dry_run=False):
    """Crawl every linked matter's mapped folders into Documents.

    Append-only; nothing is ever reconciled away. Returns
    (stats, unmatched_folder_names).
    """
    stats = _new_stats()
    unmatched = set()

    linked = list(_linked_matters())
    by_id = {m.drive_folder_id: m for m in linked if m.drive_folder_id}
    by_name = {m.drive_folder: m for m in linked if m.drive_folder}
    seen = set()

    for matter_folder in _list_children(service, root_id):
        if matter_folder.get("mimeType") != FOLDER_MIME:
            continue
        matter = by_id.get(matter_folder["id"]) or by_name.get(matter_folder["name"])
        if matter is None:
            unmatched.add(matter_folder["name"])
            continue
        if matter.pk in seen:
            # A second root folder with a linked matter's old name: ignore.
            continue
        seen.add(matter.pk)
        _bootstrap_matter(service, matter_folder, matter, dry_run, stats)

    if not dry_run:
        for matter in linked:
            if matter.pk not in seen:
                mapping_rules.record_matter_state(matter, [], folder_missing=True)

    return stats, unmatched


def _note_unmapped_folder(matter, folder_meta):
    """A new subfolder appeared under a linked matter: nudge via the badge."""
    state, _ = DriveMatterState.objects.get_or_create(matter=matter)
    entry = {"id": folder_meta["id"], "name": folder_meta.get("name", "")}
    if all(f.get("id") != entry["id"] for f in state.unmapped_folders):
        state.unmapped_folders = [*state.unmapped_folders, entry]
        state.checked_at = timezone.now()
        state.save(update_fields=["unmapped_folders", "checked_at"])


def _process_change(
    service,
    change,
    root_id,
    by_folder,
    matters_by_folder_id,
    folder_cache,
    dry_run,
    stats,
):
    file_meta = change.get("file")

    # Removal / trash: the mirror is append-only, so a removed or trashed
    # Drive file leaves its app rows untouched.
    if change.get("removed") or (file_meta and file_meta.get("trashed")):
        return
    if not file_meta:
        return

    if file_meta.get("mimeType") == FOLDER_MIME:
        # Folders: cheap bookkeeping only (renames of mapped folders, new
        # subfolders under a linked matter); structure is reconciled by the
        # nightly full pass.
        if dry_run:
            return
        mapping = by_folder.get(file_meta["id"])
        if mapping is not None:
            _refresh_mapping_path(mapping, file_meta.get("name", mapping.folder_name))
            return
        parents = file_meta.get("parents") or []
        matter = matters_by_folder_id.get(parents[0]) if parents else None
        if matter is not None and file_meta.get("name") != NOTES_FOLDER_NAME:
            _note_unmapped_folder(matter, file_meta)
        return

    chain = _walk_to_root(service, file_meta, root_id, folder_cache)
    if chain is None:
        stats["records_unresolved"] += 1
        return

    mapping = mapping_rules.resolve_mapping(chain, by_folder)
    if mapping is None:
        # Out of every mapped folder (dragged out, or under an unmapped
        # folder): the document stays, but it no longer belongs to a
        # mapping, so a later re-map of that folder leaves it alone.
        if not dry_run:
            from apps.case.models import Document

            Document.objects.filter(
                drive_file_id=file_meta["id"], drive_mapping__isnull=False
            ).update(drive_mapping=None)
        return

    if not records.is_pdf(file_meta):
        stats["records_non_pdf"] += 1
        return
    try:
        parts = [name for _, name in chain]
        records.ingest_mapped(service, file_meta, parts, mapping, dry_run, stats)
    except Exception:
        stats["records_failed"] += 1
        logger.exception("Failed to sync %s", file_meta.get("name"))


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

    state, _ = DriveSyncState.objects.get_or_create(pk=1)

    # First run or forced full: crawl everything, then capture a start token.
    if full or not state.page_token:
        stats, unmatched = bootstrap(service, root_id, dry_run)
        token = service.changes().getStartPageToken(**_page_token_args()).execute()
        if not dry_run:
            state.page_token = token["startPageToken"]
            state.unmatched_folders = sorted(unmatched)
            state.save()
        logger.info(
            "Drive bootstrap complete: %s (unmatched: %s)", stats, sorted(unmatched)
        )
        return {**stats, "unmatched": sorted(unmatched)}

    # Incremental: consume the changes delta.
    stats = _new_stats()
    unmatched = set(state.unmatched_folders or [])
    by_folder = mapping_rules.mappings_by_folder_id()
    matters_by_folder_id = {
        m.drive_folder_id: m for m in _linked_matters() if m.drive_folder_id
    }
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
                    by_folder,
                    matters_by_folder_id,
                    folder_cache,
                    dry_run,
                    stats,
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

    missing = [
        f"{m.matter.drive_folder}/{m.folder_path}"
        for m in DriveFolderMapping.objects.exclude(missing_since__isnull=True)
        .select_related("matter")
        .order_by("matter__name", "folder_path")
    ]
    return {
        "linked": check_credentials(),
        "linked_matters": _linked_matters().count(),
        "synced_records": Document.objects.filter(drive_file_id__isnull=False).count(),
        "mapped_folders": DriveFolderMapping.objects.count(),
        "missing_folders": missing,
        "matters_needing_attention": mapping_rules.matters_needing_attention(),
    }


# --------------------------------------------------------------------------- #
# Folder helpers (the Drive Folder modal, resync, drafts picker)
# --------------------------------------------------------------------------- #
def _find_child_folder(service, parent_id, name):
    """Return the child folder with the given name, or None (records resync)."""
    for child in _list_children(service, parent_id):
        if child.get("mimeType") == FOLDER_MIME and child.get("name") == name:
            return child
    return None


def get_folder(service, folder_id):
    """Folder metadata by id, or None when it is gone or trashed."""
    try:
        meta = (
            service.files()
            .get(
                fileId=folder_id,
                fields="id, name, parents, trashed, mimeType",
                supportsAllDrives=True,
            )
            .execute()
        )
    except HttpError:
        return None
    if meta.get("trashed"):
        return None
    return meta


def list_child_folders(service, parent_id):
    """Direct subfolders of a folder, as [{"id", "name"}] sorted by name."""
    folders = [
        {"id": child["id"], "name": child.get("name", "")}
        for child in _list_children(service, parent_id)
        if child.get("mimeType") == FOLDER_MIME
    ]
    return sorted(folders, key=lambda f: (f["name"].lower(), f["id"]))


def _resolve_path(service, parent_id, path):
    """Walk a cached "A/B" path under parent_id; the final folder or None."""
    folder = None
    current = parent_id
    for segment in path.split("/"):
        folder = _find_child_folder(service, current, segment)
        if folder is None:
            return None
        current = folder["id"]
    return folder


def find_matter_folder(service, root_id, matter):
    """The matter's Drive folder metadata (by id, else by name), or None.

    A name-only link that resolves gets its id stored so later lookups
    survive a rename in Drive.
    """
    if matter.drive_folder_id:
        meta = get_folder(service, matter.drive_folder_id)
        if meta is not None:
            return meta
    if matter.drive_folder:
        meta = _find_child_folder(service, root_id, matter.drive_folder)
        if meta is not None:
            Matter.objects.filter(pk=matter.pk).update(drive_folder_id=meta["id"])
            matter.drive_folder_id = meta["id"]
            return meta
    return None


def resolve_mapping_folder(service, matter_folder_id, mapping):
    """The mapped folder's metadata, resolving a legacy path to an id."""
    if mapping.folder_id:
        return get_folder(service, mapping.folder_id)
    folder = _resolve_path(service, matter_folder_id, mapping.folder_path)
    if folder is not None:
        mapping.folder_id = folder["id"]
        mapping.save(update_fields=["folder_id", "updated_at"])
    return folder


def list_root_folders():
    """Folders directly under the Drive root, as [{"id", "name"}].

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
        return list_child_folders(service, root_id)
    except HttpError:
        logger.exception("Failed to list Drive root folders")
        return []
