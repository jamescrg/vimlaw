"""Mapping-driven sync: categories, nesting, ids over names, nudges, moves."""

import pytest

import apps.drive.google as google
from apps.case.models import Document
from apps.drive.models import DriveFolderMapping, DriveMatterState
from apps.matters.models import Matter

pytestmark = pytest.mark.django_db


def _map(matter, folder_id, path, category, proceeding=None):
    return DriveFolderMapping.objects.create(
        matter=matter,
        folder_id=folder_id,
        folder_path=path,
        category=category,
        proceeding=proceeding,
    )


@pytest.fixture
def tree(fake_drive):
    fake_drive.add_folder("cf1", "Corr", parent="mf1")
    fake_drive.add_folder("df1", "Discovery", parent="mf1")
    fake_drive.add_folder("ef1", "Evidence", parent="mf1")
    fake_drive.add_folder("kd1", "Key Documents", parent="ef1")
    return fake_drive


def test_each_category_ingests_with_its_rule(matter, proceeding, tree):
    _map(matter, "cf1", "Corr", "Correspondence")
    _map(matter, "df1", "Discovery", "Discovery", proceeding)
    _map(matter, "ef1", "Evidence", "Evidence")
    tree.add_file("c1", "Letter.pdf", "cf1")
    tree.add_file("d1", "ROG.pdf", "df1")
    tree.add_file("e1", "Photo.pdf", "ef1")
    stats = google.sync(full=True)
    assert stats["records_synced"] == 3
    by_id = {d.drive_file_id: d for d in Document.objects.all()}
    assert (by_id["c1"].category, by_id["c1"].proceeding) == ("Correspondence", None)
    assert (by_id["d1"].category, by_id["d1"].proceeding) == ("Discovery", proceeding)
    assert (by_id["e1"].category, by_id["e1"].proceeding) == ("Evidence", None)


def test_unmapped_sibling_ignored_and_nudged(matter, proceeding, tree):
    _map(matter, "cf1", "Corr", "Correspondence")
    tree.add_file("e1", "Photo.pdf", "ef1")
    google.sync(full=True)
    assert Document.objects.count() == 0
    state = DriveMatterState.objects.get(matter=matter)
    assert sorted(f["name"] for f in state.unmapped_folders) == [
        "CA-2 Record",
        "Discovery",
        "Evidence",
    ]
    assert state.folder_missing is False


def test_legacy_nested_row_wins_over_top_level(matter, tree):
    """A converted Evidence/Key Documents row keeps syncing; files under
    the top-level Evidence folder only sync once Evidence itself is mapped."""
    nested = _map(matter, None, "Evidence/Key Documents", "Evidence")
    tree.add_file("k1", "Deed.pdf", "kd1")
    tree.add_file("e1", "Noise.pdf", "ef1")
    stats = google.sync(full=True)
    assert stats["records_synced"] == 1
    nested.refresh_from_db()
    assert nested.folder_id == "kd1"  # resolved from the cached path
    doc = Document.objects.get()
    assert doc.drive_mapping == nested
    assert doc.drive_path == "Smith v. Jones/Evidence/Key Documents/Deed.pdf"

    top = _map(matter, "ef1", "Evidence", "Evidence")
    google.sync(full=True)
    assert Document.objects.count() == 2
    assert Document.objects.get(drive_file_id="e1").drive_mapping == top
    assert Document.objects.get(drive_file_id="k1").drive_mapping == nested


def test_renamed_mapped_folder_keeps_syncing(matter, tree):
    mapping = _map(matter, "cf1", "Corr", "Correspondence")
    tree.rename("cf1", "Correspondence")
    tree.add_file("c1", "Letter.pdf", "cf1")
    google.sync(full=True)
    mapping.refresh_from_db()
    assert mapping.folder_path == "Correspondence"
    assert Document.objects.get().drive_path == (
        "Smith v. Jones/Correspondence/Letter.pdf"
    )


def test_renamed_matter_folder_matched_by_id(matter, proceeding, record_mapping, tree):
    tree.rename("mf1", "Smith v. Jones (2026)")
    tree.add_file("f1", "Complaint.pdf", "rf1")
    stats = google.sync(full=True)
    assert stats["records_synced"] == 1
    assert stats["unmatched"] == []
    matter.refresh_from_db()
    assert matter.drive_folder == "Smith v. Jones (2026)"


def test_name_only_link_upgraded_to_id(proceeding, record_mapping, tree):
    Matter.objects.filter(pk=proceeding.matter_id).update(drive_folder_id=None)
    tree.add_file("f1", "Complaint.pdf", "rf1")
    google.sync(full=True)
    matter = Matter.objects.get(pk=proceeding.matter_id)
    assert matter.drive_folder_id == "mf1"
    assert Document.objects.count() == 1


def test_matter_folder_missing_flagged(matter, proceeding, record_mapping, tree):
    del tree.files_by_id["mf1"]
    google.sync(full=True)
    assert DriveMatterState.objects.get(matter=matter).folder_missing is True


def test_move_between_mapped_folders_follows_new_mapping(matter, proceeding, tree):
    corr = _map(matter, "cf1", "Corr", "Correspondence")
    disc = _map(matter, "df1", "Discovery", "Discovery", proceeding)
    meta = tree.add_file("c1", "Letter.pdf", "cf1")
    google.sync(full=True)
    doc = Document.objects.get()
    assert doc.drive_mapping == corr

    tree.move("c1", "df1")
    tree.change_feed = [tree.change_for("c1")]
    google.sync()
    doc.refresh_from_db()
    assert doc.drive_mapping == disc
    assert (doc.category, doc.proceeding) == ("Discovery", proceeding)
    assert doc.drive_path == "Smith v. Jones/Discovery/Letter.pdf"
    assert meta["parents"] == ["df1"]


def test_move_out_of_mapped_folders_clears_mapping_only(matter, tree):
    corr = _map(matter, "cf1", "Corr", "Correspondence")
    tree.add_file("c1", "Letter.pdf", "cf1")
    google.sync(full=True)
    tree.move("c1", "ef1")  # Evidence is not mapped
    tree.change_feed = [tree.change_for("c1")]
    google.sync()
    doc = Document.objects.get()
    assert doc.drive_mapping is None
    assert doc.category == "Correspondence"
    # Re-mapping Corr later does not touch it.
    corr.category = "Evidence"
    corr.save()
    from apps.drive.mappings import backfill_documents

    assert backfill_documents(corr) == 0


def test_hand_edits_stand_within_same_mapping(matter, proceeding, tree):
    _map(matter, "cf1", "Corr", "Correspondence")
    tree.add_file("c1", "Letter.pdf", "cf1")
    google.sync(full=True)
    doc = Document.objects.get()
    Document.objects.filter(pk=doc.pk).update(category="Evidence")
    google.sync(full=True)
    doc.refresh_from_db()
    assert doc.category == "Evidence"


def test_new_subfolder_event_lands_in_unmapped_list(
    matter, proceeding, record_mapping, tree
):
    google.sync(full=True)  # cursor + state
    tree.add_folder("nf2", "Pleadings", parent="mf1")
    tree.change_feed = [tree.change_for("nf2")]
    google.sync()
    state = DriveMatterState.objects.get(matter=matter)
    assert {"id": "nf2", "name": "Pleadings"} in state.unmapped_folders


def test_folder_rename_event_refreshes_path(matter, proceeding, record_mapping, tree):
    google.sync(full=True)
    tree.rename("rf1", "Record - Main")
    tree.change_feed = [tree.change_for("rf1")]
    google.sync()
    record_mapping.refresh_from_db()
    assert record_mapping.folder_path == "Record - Main"


def test_trashed_ancestor_out_of_scope(matter, proceeding, record_mapping, tree):
    google.sync(full=True)
    tree.add_folder("sub", "Old", parent="rf1")
    tree.add_file("f9", "Stale.pdf", "sub")
    tree.trash("sub")
    tree.change_feed = [tree.change_for("f9")]
    stats = google.sync()
    assert stats["records_synced"] == 0
    assert stats["records_unresolved"] == 1


def test_adopted_twin_takes_folder_category(matter, tree):
    from django.core.files.base import ContentFile

    _map(matter, "cf1", "Corr", "Correspondence")
    content = b"%PDF-letter"
    manual = Document.objects.create(
        matter=matter, name="Letter", date="2026-03-01", category="Evidence"
    )
    manual.file.save(f"{manual.pk}.pdf", ContentFile(content), save=True)
    tree.add_file("c1", "2026-03-01 Letter.pdf", "cf1", content=content)
    stats = google.sync(full=True)
    assert stats["records_adopted"] == 1
    manual.refresh_from_db()
    assert manual.category == "Correspondence"
    assert manual.drive_mapping is not None


def test_sync_status_summary(matter, proceeding, record_mapping, tree):
    tree.add_file("f1", "Complaint.pdf", "rf1")
    google.sync(full=True)
    status = google.get_sync_status()
    assert status["linked_matters"] == 1
    assert status["mapped_folders"] == 1
    assert status["synced_records"] == 1
    assert status["missing_folders"] == []
    assert status["matters_needing_attention"] == 1  # unmapped Corr etc.
