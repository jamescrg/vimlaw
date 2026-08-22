"""Drive folder mappings: the rules behind the Documents tab's Drive Folder modal.

DB-only helpers (no Drive calls), safe to import from views and the sync
engine alike:

- category/proceeding rules (``normalize_rule``), name-convention
  suggestions for unmapped folders (``suggest_mapping``),
- the lookup the sync engine dispatches through (``mappings_by_folder_id``,
  ``resolve_mapping``),
- what a mapping writes onto a Document (``apply_mapping_fields``) and the
  re-map backfill (``backfill_documents``),
- the per-matter nudge state behind the Documents-tab badge
  (``record_matter_state``, ``matter_drive_status``).
"""

import difflib
import re

from django.db.models import Q
from django.utils import timezone

from .models import MAPPING_CATEGORY_CHOICES, DriveFolderMapping, DriveMatterState

# The modal's category select: the empty value means "not synced".
CATEGORY_CHOICES = [("", "Not synced")] + MAPPING_CATEGORY_CHOICES
VALID_CATEGORIES = {value for value, _ in MAPPING_CATEGORY_CHOICES}

# Folder-name conventions that pre-fill an unmapped row. Only suggestions:
# nothing syncs until the user saves the row. Record and Discovery folders
# follow the same per-proceeding pattern: a bare "Record" / "Discovery"
# suggests the primary proceeding, "Record - Appeal" / "Discovery - Appeal"
# (or "Appeal Record") the proceeding named. Evidence is deliberately NOT
# suggested: a firm's "Evidence" folders are typically the bulk pile, and
# because Save posts every row, a pre-filled Evidence would be mapped by a
# user who only came to map Corr. Evidence is always a by-hand choice.
_NAME_TO_CATEGORY = {
    "corr": "Correspondence",
    "correspondence": "Correspondence",
    "discovery": "Discovery",
    "record": "Record",
    "records": "Record",
}
_PROCEEDING_CATEGORIES = {
    "record": "Record",
    "records": "Record",
    "discovery": "Discovery",
}
_PROCEEDING_SUFFIX_RE = re.compile(
    r"^(records?|discovery)\s*[-:–—]\s*(.+)$", re.IGNORECASE
)
_PROCEEDING_PREFIX_RE = re.compile(r"^(.+?)\s+(records?|discovery)$", re.IGNORECASE)

BACKFILL_CHUNK = 500


def normalize_rule(category, proceeding):
    """Apply the category/proceeding rules; returns (category, proceeding).

    Record requires a proceeding (ValueError otherwise); Discovery may have
    one; Correspondence and Evidence never do (a given proceeding is dropped
    silently, mirroring Document.save()'s coercion in the other direction).
    """
    if category not in VALID_CATEGORIES:
        raise ValueError("Choose a category for every mapped folder.")
    if category == "Record":
        if proceeding is None:
            raise ValueError("Record folders need a proceeding.")
        return category, proceeding
    if category == "Discovery":
        return category, proceeding
    return category, None


def _match_proceeding(text, proceedings):
    """The proceeding whose nickname / display name / case number matches."""
    wanted = text.strip().lower()
    if not wanted:
        return None
    labels = {}
    for proceeding in proceedings:
        for label in (
            proceeding.nickname,
            proceeding.display_name,
            proceeding.case_number,
        ):
            if label:
                labels.setdefault(str(label).strip().lower(), proceeding)
    if wanted in labels:
        return labels[wanted]
    close = difflib.get_close_matches(wanted, list(labels), n=1, cutoff=0.6)
    return labels[close[0]] if close else None


def suggest_mapping(folder_name, proceedings):
    """(category, proceeding) a folder name suggests, or None.

    ``proceedings`` is the matter's list (primary first is ideal). A bare
    "Record" or "Discovery" folder suggests the primary proceeding (or the
    only one); "Record - X" / "Discovery - X" suggest that category plus the
    proceeding X names. A suggestion with no resolvable proceeding is still
    returned with proceeding None so the UI pre-selects the category and
    leaves the proceeding for the user.
    """
    name = (folder_name or "").strip()
    key = name.lower()
    proceedings = list(proceedings)
    if key in _NAME_TO_CATEGORY:
        category = _NAME_TO_CATEGORY[key]
        if category not in ("Record", "Discovery"):
            return category, None
        primary = next((p for p in proceedings if p.primary), None)
        if primary is None and len(proceedings) == 1:
            primary = proceedings[0]
        return category, primary
    match = _PROCEEDING_SUFFIX_RE.match(name)
    if match:
        category, text = match.group(1), match.group(2)
    else:
        match = _PROCEEDING_PREFIX_RE.match(name)
        if not match:
            return None
        text, category = match.group(1), match.group(2)
    return _PROCEEDING_CATEGORIES[category.lower()], _match_proceeding(
        text, proceedings
    )


def mappings_by_folder_id():
    """{folder_id: mapping} for every resolved mapping (the sync's lookup)."""
    qs = DriveFolderMapping.objects.exclude(folder_id__isnull=True).select_related(
        "matter", "proceeding"
    )
    return {m.folder_id: m for m in qs}


def resolve_mapping(chain, mappings):
    """The mapping governing a file, given its ancestor chain.

    ``chain`` is [(folder_id, name), ...] from just under the Drive root
    down to the file itself (as google._walk_to_root returns). The nearest
    mapped ancestor wins, so a legacy nested row ("Evidence/Key Documents")
    beats a top-level "Evidence" row for files under it.
    """
    if not chain:
        return None
    for folder_id, _name in reversed(chain[:-1]):
        mapping = mappings.get(folder_id)
        if mapping is not None:
            return mapping
    return None


def apply_mapping_fields(mapping):
    """The Document fields a mapping dictates, written together.

    Category and proceeding always travel as a pair so Document.save()'s
    "proceeding set => Record" coercion never fights the mapping.
    """
    return {
        "category": mapping.category,
        "proceeding_id": mapping.proceeding_id,
        "drive_mapping_id": mapping.id,
    }


def backfill_documents(mapping):
    """Re-map already-synced documents after the row's category/proceeding
    changed. Bulk update (no history rows, no full_clean); name, date,
    importance, labels, highlights are untouched. Returns the count."""
    from apps.case.models import Document

    ids = list(
        Document.objects.filter(drive_mapping=mapping).values_list("pk", flat=True)
    )
    fields = {
        "category": mapping.category,
        "proceeding_id": mapping.proceeding_id,
        "updated_at": timezone.now(),
    }
    for start in range(0, len(ids), BACKFILL_CHUNK):
        Document.objects.filter(pk__in=ids[start : start + BACKFILL_CHUNK]).update(
            **fields
        )
    return len(ids)


def record_matter_state(matter, live_folders, folder_missing=False):
    """Store the matter's nudge state from a live top-level folder listing.

    ``live_folders`` is [{"id", "name"}] for the matter folder's direct
    subfolders (the retired Notes folder already excluded by the caller).
    """
    mapped_ids = set(
        DriveFolderMapping.objects.filter(matter=matter)
        .exclude(folder_id__isnull=True)
        .values_list("folder_id", flat=True)
    )
    unmapped = [
        {"id": f["id"], "name": f["name"]}
        for f in live_folders
        if f["id"] not in mapped_ids
    ]
    DriveMatterState.objects.update_or_create(
        matter=matter,
        defaults={
            "unmapped_folders": unmapped,
            "folder_missing": folder_missing,
            "checked_at": timezone.now(),
        },
    )
    return unmapped


def matter_drive_status(matter):
    """DB-only summary for the Documents-tab button (never calls Drive)."""
    from apps.matters.proceedings.models import Proceeding

    state = DriveMatterState.objects.filter(matter=matter).first()
    mappings = list(DriveFolderMapping.objects.filter(matter=matter))
    linked = bool(matter.drive_folder or matter.drive_folder_id)
    unmapped = len(state.unmapped_folders) if state else 0
    missing = sum(1 for m in mappings if m.missing_since)
    with_record = {m.proceeding_id for m in mappings if m.category == "Record"}
    proceedings_without_folder = 0
    if linked:
        proceedings_without_folder = (
            Proceeding.objects.filter(matter=matter)
            .exclude(status="Concluded")
            .exclude(pk__in=with_record)
            .count()
        )
    return {
        "linked": linked,
        "folder": matter.drive_folder,
        "folder_missing": bool(state and state.folder_missing),
        "mapped": len(mappings),
        "unmapped": unmapped,
        "missing": missing,
        "proceedings_without_folder": proceedings_without_folder,
        "attention": unmapped + missing + proceedings_without_folder,
        "checked_at": state.checked_at if state else None,
    }


def matters_needing_attention():
    """Count for the integrations page: matters with unmapped or missing folders."""
    from apps.matters.models import Matter

    flagged = set(
        DriveMatterState.objects.filter(
            Q(folder_missing=True) | ~Q(unmapped_folders=[])
        ).values_list("matter_id", flat=True)
    )
    flagged |= set(
        DriveFolderMapping.objects.exclude(missing_since__isnull=True).values_list(
            "matter_id", flat=True
        )
    )
    return Matter.objects.filter(pk__in=flagged).count()
