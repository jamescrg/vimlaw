"""Draft-link mechanics: Drive listing, link creation, text refresh.

The AI's view of the draft is one text field (DraftLink.doc_text), written
from three sources with one freshness story: a Drive fetch at link time,
every companion push, and a re-fetch here when the text has gone stale with
no companion connected.
"""

import logging
from datetime import timedelta

from django.utils import timezone
from googleapiclient.errors import HttpError

from apps.drafts.models import DraftLink
from apps.drive import convert, google

logger = logging.getLogger(__name__)

# How deep under the matter's Drive folder the ODT listing will walk.
MAX_LIST_DEPTH = 4

# With no companion connected, re-fetch the draft from Drive when the stored
# text is older than this (the user may have edited and synced the file).
STALE_AFTER = timedelta(minutes=5)


class DraftError(Exception):
    """A drafting operation could not be performed."""


def list_matter_odt_files(matter):
    """ODT files under the matter's Drive folder, as picker dicts.

    Returns [{"id", "name", "path", "modifiedTime"}, ...] sorted by folder
    path then name. Fails soft to [] (Drive unlinked, folder missing, API
    error) so the picker degrades instead of 500ing.
    """
    if not matter.drive_folder or not google.check_credentials():
        return []
    try:
        service = google.build_service()
        if not service:
            return []
        root_id = google._find_root_folder(service)
        if not root_id:
            return []
        folder = google._find_child_folder(service, root_id, matter.drive_folder)
        if not folder:
            return []

        files = []

        def walk(folder_id, path, depth):
            if depth > MAX_LIST_DEPTH:
                return
            for child in google._list_children(service, folder_id):
                if child.get("mimeType") == google.FOLDER_MIME:
                    walk(child["id"], f"{path}{child['name']}/", depth + 1)
                elif child.get("name", "").lower().endswith(".odt"):
                    files.append(
                        {
                            "id": child["id"],
                            "name": child["name"],
                            "path": path,
                            "modifiedTime": child.get("modifiedTime", ""),
                        }
                    )

        walk(folder["id"], "", 0)
        return sorted(files, key=lambda f: (f["path"], f["name"].lower()))
    except HttpError:
        logger.exception("Failed to list ODT files for matter %s", matter.id)
        return []


def _fetch_drive_text(drive_file_id):
    """(name, markdown) for a Drive ODT, or raise DraftError."""
    if not google.check_credentials():
        raise DraftError("Google Drive is not connected.")
    service = google.build_service()
    if not service:
        raise DraftError("Google Drive is not connected.")
    try:
        meta = (
            service.files()
            .get(
                fileId=drive_file_id, fields=google.FILE_FIELDS, supportsAllDrives=True
            )
            .execute()
        )
        content = google._download(service, meta)
    except HttpError as exc:
        raise DraftError(f"Could not fetch the file from Drive: {exc}") from exc
    name = meta.get("name", "")
    if not name.lower().endswith(".odt"):
        raise DraftError("Drafts must be .odt files.")
    return name, convert.to_markdown(content, ".odt")


def create_link(conversation, drive_file_id):
    """Link the conversation to a Drive ODT, snapshotting its text."""
    if getattr(conversation, "draft_link", None):
        raise DraftError("This conversation already has a linked draft.")
    name, text = _fetch_drive_text(drive_file_id)
    link = DraftLink.objects.create(
        conversation=conversation,
        drive_file_id=drive_file_id,
        name=name,
        doc_text=text,
        doc_text_at=timezone.now(),
    )
    logger.info("Linked draft %r to conversation %s", name, conversation.id)
    return link


def refresh_if_stale(link):
    """Re-fetch the draft text from Drive when it is stale and unwatched.

    With a companion connected the pushes keep doc_text fresh and Drive may
    lag the live document, so never re-fetch then. Fails soft: the stored
    text is still a usable context.
    """
    if link.companion_active:
        return
    if link.doc_text_at and timezone.now() - link.doc_text_at < STALE_AFTER:
        return
    try:
        _, text = _fetch_drive_text(link.drive_file_id)
    except DraftError as exc:
        logger.warning("Stale-refresh failed for link %s: %s", link.id, exc)
        return
    link.doc_text = text
    link.doc_text_at = timezone.now()
    link.save(update_fields=["doc_text", "doc_text_at"])
