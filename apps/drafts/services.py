"""Draft-session mechanics: Drive listing/snapshot, edit rounds, publish.

Every version's ODT and PDF live on default storage (S3 in prod), so the UNO
work round-trips through a temp directory: pull bytes from storage, run
LibreOffice, save the results back. The applier itself is atomic; a failed
round creates no version and leaves the session on its current one.
"""

import logging
import tempfile
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils import timezone
from googleapiclient.errors import HttpError

from apps.case.ai.models import Conversation
from apps.drafts.models import DraftSession, DraftVersion
from apps.drive import convert, google, redline

logger = logging.getLogger(__name__)

# How deep under the matter's Drive folder the ODT listing will walk.
MAX_LIST_DEPTH = 4

# Default model for new draft conversations (an existing dispatch key).
DEFAULT_DRAFT_LLM = "claude-opus"


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


def create_session(matter, drive_file_id, user):
    """Open a drafting session: snapshot the Drive ODT and build version 0."""
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

    if not meta.get("name", "").lower().endswith(".odt"):
        raise DraftError("Drafting sessions only support .odt files.")

    conversation = Conversation.objects.create(
        title=f"Draft: {meta['name']}"[:200],
        llm=DEFAULT_DRAFT_LLM,
        vet_citations=False,
        user=user,
    )
    session = DraftSession.objects.create(
        matter=matter,
        conversation=conversation,
        user=user,
        drive_file_id=drive_file_id,
        name=meta["name"],
        drive_modified=meta.get("modifiedTime", ""),
    )
    try:
        _create_version_zero(session, content)
    except Exception:
        # No version 0 means no usable session; don't leave a husk behind.
        session.delete()
        conversation.delete()
        raise
    return session


def _create_version_zero(session, odt_bytes):
    with tempfile.TemporaryDirectory(prefix="draft-v0-") as tmp:
        src = Path(tmp) / "draft.odt"
        src.write_bytes(odt_bytes)
        pdf = Path(tmp) / "draft.pdf"
        redline.export_pdf(src, pdf)
        pdf_bytes = pdf.read_bytes()
    return _save_version(session, 0, odt_bytes, pdf_bytes, [])


def apply_edit_round(session, edits):
    """Apply one round of RedlineEdits to the current version → new version.

    Raises redline.RedlineError (unmatched/ambiguous/LibreOffice failure) or
    DraftError; on failure no version is created.
    """
    if session.status != "drafting":
        raise DraftError("This session is no longer accepting edits.")
    current = session.current_version
    if current is None or not current.odt_file:
        raise DraftError("The session has no working copy to edit.")

    with tempfile.TemporaryDirectory(prefix="draft-edit-") as tmp:
        src = Path(tmp) / "src.odt"
        with current.odt_file.open("rb") as handle:
            src.write_bytes(handle.read())
        out = Path(tmp) / "out.odt"
        pdf = Path(tmp) / "out.pdf"
        redline.apply_redline_edits(src, edits, output_path=out, pdf_path=pdf)
        odt_bytes = out.read_bytes()
        pdf_bytes = pdf.read_bytes()

    version = _save_version(
        session,
        current.seq + 1,
        odt_bytes,
        pdf_bytes,
        [redline.edit_to_dict(e) for e in edits],
    )
    session.save(update_fields=["updated_at"])
    return version


def _save_version(session, seq, odt_bytes, pdf_bytes, edits):
    facsimile = convert.to_markdown(odt_bytes, ".odt")
    version = DraftVersion(session=session, seq=seq, facsimile=facsimile, edits=edits)
    version.odt_file.save(f"v{seq}.odt", ContentFile(odt_bytes), save=False)
    version.pdf_file.save(f"v{seq}.pdf", ContentFile(pdf_bytes), save=False)
    version.save()
    return version


def publish_session(session):
    """The human gate: settle the session and purge working blobs.

    The final version's files are kept for download; every earlier version
    keeps only its facsimile and edit list. (Drive write-back is the planned
    next phase; until then "publish" means the redlined ODT is final and
    downloadable.)
    """
    if session.status != "drafting":
        raise DraftError("This session was already settled.")
    final = session.current_version
    if final is None:
        raise DraftError("Nothing to publish.")
    for version in session.versions.exclude(pk=final.pk):
        _purge_blobs(version)
    session.status = "published"
    session.published_at = timezone.now()
    session.save()
    logger.info("Published draft session %s at v%s", session.id, final.seq)
    return final


def abandon_session(session):
    """Discard the session's working blobs; keep the paper trail."""
    if session.status == "published":
        raise DraftError("A published session cannot be discarded.")
    for version in session.versions.all():
        _purge_blobs(version)
    session.status = "abandoned"
    session.save()


def _purge_blobs(version):
    """Clear the version's file fields; django_cleanup deletes the storage
    objects on save."""
    if not version.odt_file and not version.pdf_file:
        return
    version.odt_file = None
    version.pdf_file = None
    version.save(update_fields=["odt_file", "pdf_file"])
