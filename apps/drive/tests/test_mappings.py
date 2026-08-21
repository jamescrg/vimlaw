"""Mapping rules: suggestions, category/proceeding rules, backfill scoping."""

import pytest

from apps.case.models import Document
from apps.drive import mappings
from apps.drive.models import DriveFolderMapping
from apps.matters.proceedings.models import Proceeding

pytestmark = pytest.mark.django_db


@pytest.fixture
def appeal(matter):
    return Proceeding.objects.create(
        matter=matter, nickname="Appeal", forum="Court of Appeals", case_number="A26-9"
    )


def test_suggest_category_names(matter, proceeding):
    procs = [proceeding]
    assert mappings.suggest_mapping("Corr", procs) == ("Correspondence", None)
    assert mappings.suggest_mapping("correspondence", procs) == ("Correspondence", None)
    assert mappings.suggest_mapping("Discovery", procs) == ("Discovery", proceeding)
    # Evidence is never suggested: mapping the bulk evidence pile is a
    # by-hand decision (Save would otherwise carry a pre-filled row along).
    assert mappings.suggest_mapping("Evidence", procs) is None
    assert mappings.suggest_mapping("Key Documents", procs) is None
    assert mappings.suggest_mapping("Photos", procs) is None


def test_suggest_record_picks_primary(matter, proceeding, appeal):
    assert mappings.suggest_mapping("Record", [proceeding, appeal]) == (
        "Record",
        proceeding,
    )


def test_suggest_record_with_nickname(matter, proceeding, appeal):
    procs = [proceeding, appeal]
    assert mappings.suggest_mapping("Record - Appeal", procs) == ("Record", appeal)
    assert mappings.suggest_mapping("Record: appeal", procs) == ("Record", appeal)
    assert mappings.suggest_mapping("Appeal Record", procs) == ("Record", appeal)
    assert mappings.suggest_mapping("Record - A26-9", procs) == ("Record", appeal)
    # Close match still resolves; nonsense leaves the proceeding open.
    assert mappings.suggest_mapping("Record - Appeals", procs) == ("Record", appeal)
    assert mappings.suggest_mapping("Record - Zebra", procs) == ("Record", None)


def test_suggest_discovery_follows_record_pattern(matter, proceeding, appeal):
    procs = [proceeding, appeal]
    assert mappings.suggest_mapping("Discovery", procs) == ("Discovery", proceeding)
    assert mappings.suggest_mapping("Discovery - Appeal", procs) == (
        "Discovery",
        appeal,
    )
    assert mappings.suggest_mapping("Appeal Discovery", procs) == ("Discovery", appeal)


def test_suggest_record_without_proceedings(matter):
    assert mappings.suggest_mapping("Record", []) == ("Record", None)
    assert mappings.suggest_mapping("Discovery", []) == ("Discovery", None)


def test_normalize_rule(proceeding):
    assert mappings.normalize_rule("Record", proceeding) == ("Record", proceeding)
    assert mappings.normalize_rule("Discovery", proceeding) == ("Discovery", proceeding)
    assert mappings.normalize_rule("Discovery", None) == ("Discovery", None)
    assert mappings.normalize_rule("Correspondence", proceeding) == (
        "Correspondence",
        None,
    )
    assert mappings.normalize_rule("Evidence", proceeding) == ("Evidence", None)
    with pytest.raises(ValueError):
        mappings.normalize_rule("Record", None)
    with pytest.raises(ValueError):
        mappings.normalize_rule("Bogus", None)


def test_resolve_mapping_nearest_ancestor(matter, proceeding):
    top = DriveFolderMapping.objects.create(
        matter=matter, folder_id="ef1", folder_path="Evidence", category="Evidence"
    )
    nested = DriveFolderMapping.objects.create(
        matter=matter,
        folder_id="kd1",
        folder_path="Evidence/Key Documents",
        category="Evidence",
    )
    by_id = {"ef1": top, "kd1": nested}
    chain = [
        ("mf1", "Smith"),
        ("ef1", "Evidence"),
        ("kd1", "Key Documents"),
        ("f", "x.pdf"),
    ]
    assert mappings.resolve_mapping(chain, by_id) is nested
    assert mappings.resolve_mapping(chain[:2] + [("f", "y.pdf")], by_id) is top
    assert mappings.resolve_mapping([("mf1", "Smith"), ("f", "z.pdf")], by_id) is None
    assert mappings.resolve_mapping(None, by_id) is None


def test_backfill_only_touches_documents_of_that_mapping(matter, proceeding, appeal):
    mapping = DriveFolderMapping.objects.create(
        matter=matter,
        folder_id="rf1",
        folder_path="Record",
        category="Record",
        proceeding=proceeding,
    )
    mine = Document.objects.create(
        matter=matter,
        name="Mine",
        category="Record",
        proceeding=proceeding,
        drive_file_id="f1",
        drive_mapping=mapping,
        importance=7,
    )
    other = Document.objects.create(
        matter=matter, name="Other", category="Record", proceeding=proceeding
    )
    mapping.category = "Discovery"
    mapping.proceeding = appeal
    mapping.save()
    assert mappings.backfill_documents(mapping) == 1
    mine.refresh_from_db()
    other.refresh_from_db()
    assert (mine.category, mine.proceeding, mine.importance) == ("Discovery", appeal, 7)
    assert (other.category, other.proceeding) == ("Record", proceeding)


def test_backfill_to_evidence_clears_proceeding(matter, proceeding):
    mapping = DriveFolderMapping.objects.create(
        matter=matter,
        folder_id="rf1",
        folder_path="Record",
        category="Record",
        proceeding=proceeding,
    )
    doc = Document.objects.create(
        matter=matter,
        name="Doc",
        category="Record",
        proceeding=proceeding,
        drive_file_id="f1",
        drive_mapping=mapping,
    )
    mapping.category = "Evidence"
    mapping.proceeding = None
    mapping.save()
    mappings.backfill_documents(mapping)
    doc.refresh_from_db()
    assert (doc.category, doc.proceeding) == ("Evidence", None)


def test_matter_drive_status_counts(matter, proceeding, appeal):
    from apps.drive.models import DriveMatterState

    DriveFolderMapping.objects.create(
        matter=matter,
        folder_id="rf1",
        folder_path="Record",
        category="Record",
        proceeding=proceeding,
    )
    DriveMatterState.objects.create(
        matter=matter, unmapped_folders=[{"id": "x", "name": "Corr"}]
    )
    status = mappings.matter_drive_status(matter)
    assert status["linked"] is True
    assert status["mapped"] == 1
    assert status["unmapped"] == 1
    assert status["proceedings_without_folder"] == 1  # the appeal
    assert status["attention"] == 2
    appeal.status = "Concluded"
    appeal.save()
    assert mappings.matter_drive_status(matter)["proceedings_without_folder"] == 0
