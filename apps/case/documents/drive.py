"""Documents tab: the Drive Folder modal.

One workflow links a matter to its Google Drive folder and maps that
folder's top-level subfolders to document categories (and, for Record /
Discovery, proceedings). The sync engine (apps/drive) ingests PDFs under
mapped folders; everything else in Drive is ignored. See
apps.drive.models.DriveFolderMapping and apps.drive.mappings for the rules.

Responses follow the project's modal contract: GETs render into
#htmx-modal-container; a successful POST answers 204 + HX-Refresh (the
modal closes, the Documents tab reloads with the new badge); validation
problems answer 200 with an error fragment swapped into #drive-folder-error.
"""

import logging

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.html import escape
from django.views.decorators.http import require_POST
from googleapiclient.errors import HttpError

import apps.drive.google as drive_google
from apps.case.views import get_matter_from_url
from apps.drive import (
    mappings as mapping_rules,
    records,
)
from apps.drive.models import DriveFolderMapping, DriveMatterState
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding

logger = logging.getLogger(__name__)

LEGACY_KEY = "legacy-"


def _error(message):
    """200 so HTMX swaps the message into the modal's error slot."""
    return HttpResponse(f'<p class="error-text">{escape(message)}</p>')


def _proceedings(matter):
    return list(Proceeding.objects.filter(matter=matter).order_by("-primary", "id"))


def _other_linked_matters(matter):
    return Matter.objects.exclude(pk=matter.pk).filter(
        Q(drive_folder_id__isnull=False)
        | (Q(drive_folder__isnull=False) & ~Q(drive_folder=""))
    )


def _root_folder_rows(matter):
    """Folders under the Drive root, marking those linked to other matters."""
    others = list(_other_linked_matters(matter))
    by_id = {m.drive_folder_id: m for m in others if m.drive_folder_id}
    by_name = {m.drive_folder: m for m in others if m.drive_folder}
    rows = []
    for folder in drive_google.list_root_folders():
        taken = by_id.get(folder["id"]) or by_name.get(folder["name"])
        rows.append({"id": folder["id"], "name": folder["name"], "taken_by": taken})
    return rows


def _live_subfolders(service, folder_id):
    """Top-level subfolders of a matter folder, Notes excluded; None on error."""
    try:
        return [
            f
            for f in drive_google.list_child_folders(service, folder_id)
            if f["name"] != drive_google.NOTES_FOLDER_NAME
        ]
    except HttpError:
        logger.exception("Failed to list Drive subfolders of %s", folder_id)
        return None


def _row(key, name, category, proceeding_id, **flags):
    row = {
        "key": key,
        "name": name,
        "category": category or "",
        "proceeding_id": proceeding_id,
        "suggested": False,
        "saved": False,
        "nested": False,
        "missing": False,
    }
    row.update(flags)
    return row


def _mapping_rows(service, matter, folder_id, proceedings, include_saved):
    """Rows for the mapping table: live top-level folders plus saved rows.

    Live folders without a mapping are pre-filled from the name
    conventions (``suggested``); saved rows whose folder is not in the live
    list are appended flagged ``missing`` (gone from Drive) or ``nested``
    (legacy rows such as Evidence/Key Documents), changeable or removable
    but never newly creatable. Legacy rows without a folder id are resolved
    by name while we are here. Returns (rows, live) with live None when
    Drive could not be listed.
    """
    live = _live_subfolders(service, folder_id)
    if live is None:
        return [], None
    saved = (
        list(
            DriveFolderMapping.objects.filter(matter=matter).select_related(
                "proceeding"
            )
        )
        if include_saved
        else []
    )
    live_by_name = {}
    for folder in live:
        live_by_name.setdefault(folder["name"], []).append(folder)
    by_id = {}
    for mapping in saved:
        if not mapping.folder_id and not mapping.is_nested:
            matches = live_by_name.get(mapping.folder_path, [])
            if len(matches) == 1:
                mapping.folder_id = matches[0]["id"]
                mapping.save(update_fields=["folder_id", "updated_at"])
        if mapping.folder_id:
            by_id[mapping.folder_id] = mapping

    rows = []
    for folder in live:
        mapping = by_id.get(folder["id"])
        if mapping is not None:
            if not mapping.is_nested and mapping.folder_path != folder["name"]:
                mapping.folder_path = folder["name"][:1024]
                mapping.save(update_fields=["folder_path", "updated_at"])
            rows.append(
                _row(
                    folder["id"],
                    folder["name"],
                    mapping.category,
                    mapping.proceeding_id,
                    saved=True,
                )
            )
            continue
        suggestion = mapping_rules.suggest_mapping(folder["name"], proceedings)
        category, proceeding = suggestion or ("", None)
        rows.append(
            _row(
                folder["id"],
                folder["name"],
                category,
                proceeding.pk if proceeding else None,
                suggested=suggestion is not None,
            )
        )

    live_ids = {folder["id"] for folder in live}
    for mapping in saved:
        if mapping.folder_id and mapping.folder_id in live_ids:
            continue
        rows.append(
            _row(
                mapping.folder_id or f"{LEGACY_KEY}{mapping.pk}",
                mapping.folder_path,
                mapping.category,
                mapping.proceeding_id,
                saved=True,
                nested=mapping.is_nested,
                missing=(
                    mapping.missing_since is not None
                    or (not mapping.is_nested and not mapping.folder_id)
                    or (not mapping.is_nested and mapping.folder_id not in live_ids)
                ),
            )
        )
    return rows, live


def _service_and_root():
    service = drive_google.build_service()
    if not service:
        return None, None
    return service, drive_google._find_root_folder(service)


@login_required
def drive_folder_modal(request, matter_id):
    """The modal: pick the matter folder, then map its subfolders."""
    matter, _ = get_matter_from_url(request, matter_id)
    linked = drive_google.check_credentials()
    proceedings = _proceedings(matter)

    root_folders = []
    rows, live = [], None
    if linked:
        root_folders = _root_folder_rows(matter)
        service, root_id = _service_and_root()
        if service and root_id and matter.drive_folder and not matter.drive_folder_id:
            # Link made before folder ids were stored: resolve it now.
            drive_google.find_matter_folder(service, root_id, matter)
        if service and matter.drive_folder_id:
            rows, live = _mapping_rows(
                service, matter, matter.drive_folder_id, proceedings, True
            )

    context = {
        "matter": matter,
        "linked": linked,
        "root_folders": root_folders,
        "current_folder_id": matter.drive_folder_id,
        "current_folder_name": matter.drive_folder,
        "picking": not matter.drive_folder_id,
        "folder_name": matter.drive_folder,
        "rows": rows,
        "live_ok": live is not None,
        "proceedings": proceedings,
        "categories": mapping_rules.CATEGORY_CHOICES,
    }
    return render(request, "case/documents/drive-folder-modal.html", context)


@login_required
def drive_mapping_rows(request, matter_id):
    """Step-2 partial for a (possibly different) matter folder."""
    matter, _ = get_matter_from_url(request, matter_id)
    folder_id = request.GET.get("matter_folder", "").strip()
    folder_name = request.GET.get("folder_name", "").strip()
    proceedings = _proceedings(matter)
    rows, live = [], None
    if folder_id and drive_google.check_credentials():
        service, _root = _service_and_root()
        if service:
            rows, live = _mapping_rows(
                service,
                matter,
                folder_id,
                proceedings,
                include_saved=(folder_id == matter.drive_folder_id),
            )
    context = {
        "matter": matter,
        "folder_name": folder_name or matter.drive_folder,
        "rows": rows,
        "live_ok": live is not None,
        "proceedings": proceedings,
        "categories": mapping_rules.CATEGORY_CHOICES,
    }
    return render(request, "case/documents/drive-mapping-rows.html", context)


def _queue_resync_mapping(mapping):
    """Resync via django-q so a large folder doesn't block the request."""
    try:
        from django_q.tasks import async_task

        async_task("apps.drive.records.resync_mapping_by_id", mapping.id)
    except Exception:
        records.resync_mapping(mapping)


def _parse_rows(post, proceedings):
    """Validate the posted mapping rows.

    Returns ({key: (category, proceeding)}, error). A category of "" means
    the row is unmapped; keys are Drive folder ids or "legacy-<pk>".
    """
    by_pk = {p.pk: p for p in proceedings}
    parsed = {}
    for field, raw_category in post.items():
        if not field.startswith("category_"):
            continue
        key = field[len("category_") :]
        category = raw_category.strip()
        raw_proceeding = post.get(f"proceeding_{key}", "").strip()
        proceeding = None
        if raw_proceeding:
            proceeding = (
                by_pk.get(int(raw_proceeding)) if raw_proceeding.isdigit() else None
            )
            if proceeding is None:
                return None, "That proceeding does not belong to this matter."
        if not category:
            parsed[key] = ("", None)
            continue
        try:
            parsed[key] = mapping_rules.normalize_rule(category, proceeding)
        except ValueError as exc:
            return None, str(exc)
    return parsed, None


@login_required
@require_POST
def drive_folder_save(request, matter_id):
    """Save the matter folder and its subfolder mappings in one go."""
    matter, _ = get_matter_from_url(request, matter_id)
    if not drive_google.check_credentials():
        return _error("Google Drive is not connected.")

    folder_id = request.POST.get("matter_folder", "").strip() or matter.drive_folder_id
    if not folder_id:
        return _error("Choose the matter's Drive folder first.")

    clash = _other_linked_matters(matter).filter(drive_folder_id=folder_id).first()
    if clash:
        return _error(
            f'"{clash.drive_folder}" is already linked to {clash}. Unlink it there first.'
        )

    service, root_id = _service_and_root()
    if not service or not root_id:
        return _error("Google Drive could not be reached. Try again in a moment.")

    folder_meta = drive_google.get_folder(service, folder_id)
    if folder_meta is None:
        return _error(
            "That folder could not be found in Drive. Reopen this dialog and pick again."
        )
    name_clash = (
        _other_linked_matters(matter)
        .filter(drive_folder_id__isnull=True, drive_folder=folder_meta.get("name"))
        .first()
    )
    if name_clash:
        return _error(
            f'"{folder_meta.get("name")}" is already linked to {name_clash}. Unlink it there first.'
        )

    proceedings = _proceedings(matter)
    parsed, error = _parse_rows(request.POST, proceedings)
    if error:
        return _error(error)

    live = _live_subfolders(service, folder_id)
    if live is None:
        return _error(
            "Drive could not list that folder's subfolders. Try again in a moment."
        )
    live_by_id = {f["id"]: f for f in live}

    folder_changed = folder_id != matter.drive_folder_id
    changed = []
    with transaction.atomic():
        if folder_changed:
            if matter.drive_folder_id:
                # Mappings were children of the old folder; they do not carry over.
                DriveFolderMapping.objects.filter(matter=matter).delete()
                DriveMatterState.objects.filter(matter=matter).delete()
            matter.drive_folder = folder_meta.get("name", "")[:255]
            matter.drive_folder_id = folder_meta["id"]
            matter.save(update_fields=["drive_folder", "drive_folder_id"])

        existing = {}
        for mapping in DriveFolderMapping.objects.filter(matter=matter):
            existing[mapping.folder_id or f"{LEGACY_KEY}{mapping.pk}"] = mapping

        for key, (category, proceeding) in parsed.items():
            mapping = existing.get(key)
            if not category:
                if mapping is not None:
                    mapping.delete()  # documents keep their category/proceeding
                continue
            proceeding_id = proceeding.pk if proceeding else None
            if mapping is None:
                folder = live_by_id.get(key)
                if folder is None:
                    # Not a current subfolder (stale dialog); nothing to map.
                    continue
                mapping = DriveFolderMapping.objects.create(
                    matter=matter,
                    folder_id=key,
                    folder_path=folder["name"][:1024],
                    category=category,
                    proceeding=proceeding,
                )
                changed.append(mapping)
                continue
            if mapping.category != category or mapping.proceeding_id != proceeding_id:
                mapping.category = category
                mapping.proceeding = proceeding
                mapping.save(update_fields=["category", "proceeding", "updated_at"])
                changed.append(mapping)
            folder = live_by_id.get(mapping.folder_id)
            if (
                folder
                and not mapping.is_nested
                and mapping.folder_path != folder["name"]
            ):
                mapping.folder_path = folder["name"][:1024]
                mapping.save(update_fields=["folder_path", "updated_at"])

        for mapping in changed:
            mapping_rules.backfill_documents(mapping)
        mapping_rules.record_matter_state(matter, live)

    # After the atomic block, so the task sees the committed rows.
    for mapping in changed:
        _queue_resync_mapping(mapping)
    return HttpResponse(status=204, headers={"HX-Refresh": "true"})


@login_required
@require_POST
def drive_folder_unlink(request, matter_id):
    """Unlink the matter's Drive folder; synced documents stay in the app."""
    matter, _ = get_matter_from_url(request, matter_id)
    with transaction.atomic():
        DriveFolderMapping.objects.filter(matter=matter).delete()
        DriveMatterState.objects.filter(matter=matter).delete()
        matter.drive_folder = None
        matter.drive_folder_id = None
        matter.save(update_fields=["drive_folder", "drive_folder_id"])
    return HttpResponse(status=204, headers={"HX-Refresh": "true"})
