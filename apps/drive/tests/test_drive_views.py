"""The Documents-tab Drive Folder modal: listing, suggestions, save, unlink."""

import pytest
from django.urls import reverse

from apps.case.models import Document
from apps.drive.models import DriveFolderMapping, DriveMatterState
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _queued(monkeypatch):
    """Record queued resyncs instead of hitting django-q / Drive."""
    calls = []
    monkeypatch.setattr(
        "apps.case.documents.drive._queue_resync_mapping",
        lambda mapping: calls.append(mapping.id),
    )
    return calls


@pytest.fixture
def tree(fake_drive):
    fake_drive.add_folder("cf1", "Corr", parent="mf1")
    fake_drive.add_folder("rf2", "Record - Appeal", parent="mf1")
    fake_drive.add_folder("mf2", "Other Matter", parent="root1")
    return fake_drive


def _modal(client, matter):
    return client.get(reverse("case:documents-drive-modal", args=[matter.id]))


def _save(client, matter, data):
    return client.post(reverse("case:documents-drive-save", args=[matter.id]), data)


def test_modal_lists_root_folders_and_marks_taken(client, matter, proceeding, tree):
    Matter.objects.create(
        name="Other", status="Open", drive_folder_id="mf2", drive_folder="Other Matter"
    )
    body = _modal(client, matter).content.decode()
    assert "Smith v. Jones" in body
    assert "Other Matter" in body and "linked to Other" in body
    assert (
        'name="matter_folder" value="mf1"' in body.replace("\n", " ").replace("  ", " ")
        or 'value="mf1"' in body
    )


def test_modal_prefills_suggestions_and_saved_rows(
    client, matter, proceeding, record_mapping, tree
):
    appeal = Proceeding.objects.create(matter=matter, nickname="Appeal")
    body = _modal(client, matter).content.decode()
    # Saved row: CA-2 Record as Record on Main (no "suggested" note).
    assert 'name="category_rf1"' in body
    # Suggestions for live folders.
    assert 'name="category_cf1"' in body and "suggested" in body
    assert 'name="category_rf2"' in body
    assert f'value="{appeal.id}" selected' in " ".join(body.split())
    assert "Notes" not in body.split("2. Folder mapping")[1]


def test_matter_without_proceedings_gets_a_hint_not_an_empty_select(
    client, matter, tree
):
    """An empty proceeding select reads as a dropdown that will not open."""
    body = _modal(client, matter).content.decode()
    assert 'name="proceeding_cf1"' not in body
    assert "No proceedings yet" in body
    assert reverse("matters:proceedings-index", args=[matter.id]) in body


def test_placeholder_label_rendered_server_side(
    client, matter, proceeding, record_mapping, tree
):
    """The placeholder must read correctly before Alpine hydrates."""
    body = " ".join(_modal(client, matter).content.decode().split())
    assert 'name="proceeding_rf1"' in body
    # Record row placeholder, and a not-applicable one for an unmapped row.
    assert "Required" in body
    assert "Not applicable" in body


def test_hidden_folders_are_not_listed(client, matter, proceeding, tree):
    tree.add_folder("hid1", ".claude", parent="mf1")
    body = _modal(client, matter).content.decode()
    assert ".claude" not in body
    assert 'name="category_hid1"' not in body


def test_modal_resolves_legacy_name_only_link(client, matter, proceeding, tree):
    Matter.objects.filter(pk=matter.pk).update(drive_folder_id=None)
    _modal(client, matter)
    matter.refresh_from_db()
    assert matter.drive_folder_id == "mf1"


def test_rows_partial_for_another_folder(client, matter, proceeding, tree):
    tree.add_folder("xf1", "Discovery", parent="mf2")
    response = client.get(
        reverse("case:documents-drive-rows", args=[matter.id]),
        {"matter_folder": "mf2", "folder_name": "Other Matter"},
    )
    body = response.content.decode()
    assert 'name="category_xf1"' in body
    assert "Other Matter" in body


def test_save_links_folder_creates_mappings_and_queues(
    client, matter, proceeding, tree, _queued
):
    Matter.objects.filter(pk=matter.pk).update(drive_folder=None, drive_folder_id=None)
    appeal = Proceeding.objects.create(matter=matter, nickname="Appeal")
    response = _save(
        client,
        matter,
        {
            "matter_folder": "mf1",
            "category_cf1": "Correspondence",
            "category_rf1": "Record",
            "proceeding_rf1": proceeding.id,
            "category_rf2": "Record",
            "proceeding_rf2": appeal.id,
        },
    )
    assert response.status_code == 204
    matter.refresh_from_db()
    assert (matter.drive_folder, matter.drive_folder_id) == ("Smith v. Jones", "mf1")
    rows = {m.folder_id: m for m in DriveFolderMapping.objects.filter(matter=matter)}
    assert rows["cf1"].category == "Correspondence" and rows["cf1"].proceeding is None
    assert rows["rf1"].proceeding == proceeding
    assert rows["rf2"].proceeding == appeal
    assert sorted(_queued) == sorted(m.id for m in rows.values())
    state = DriveMatterState.objects.get(matter=matter)
    assert state.unmapped_folders == []


def test_save_only_queues_changed_rows_and_backfills(
    client, matter, proceeding, record_mapping, tree, _queued
):
    doc = Document.objects.create(
        matter=matter,
        name="Complaint",
        category="Record",
        proceeding=proceeding,
        drive_file_id="f1",
        drive_mapping=record_mapping,
    )
    response = _save(
        client,
        matter,
        {
            "category_rf1": "Discovery",
            "proceeding_rf1": proceeding.id,
            "category_cf1": "",
            "category_rf2": "",
        },
    )
    assert response.status_code == 204
    assert _queued == [record_mapping.id]
    doc.refresh_from_db()
    assert doc.category == "Discovery"
    record_mapping.refresh_from_db()
    assert record_mapping.category == "Discovery"


def test_save_unchanged_row_queues_nothing(
    client, matter, proceeding, record_mapping, tree, _queued
):
    response = _save(
        client, matter, {"category_rf1": "Record", "proceeding_rf1": proceeding.id}
    )
    assert response.status_code == 204
    assert _queued == []


def test_record_without_proceeding_rejected(client, matter, proceeding, tree, _queued):
    response = _save(client, matter, {"category_rf2": "Record", "proceeding_rf2": ""})
    assert response.status_code == 200
    assert "need a proceeding" in response.content.decode()
    assert DriveFolderMapping.objects.count() == 0
    assert _queued == []


def test_correspondence_drops_proceeding(client, matter, proceeding, tree):
    _save(
        client,
        matter,
        {"category_cf1": "Correspondence", "proceeding_cf1": proceeding.id},
    )
    assert DriveFolderMapping.objects.get(folder_id="cf1").proceeding is None


def test_foreign_proceeding_rejected(client, matter, proceeding, tree):
    other_matter = Matter.objects.create(name="Other", status="Open")
    foreign = Proceeding.objects.create(matter=other_matter, nickname="X")
    response = _save(
        client, matter, {"category_rf2": "Record", "proceeding_rf2": foreign.id}
    )
    assert "does not belong" in response.content.decode()


def test_unmap_keeps_documents(
    client, matter, proceeding, record_mapping, tree, _queued
):
    Document.objects.create(
        matter=matter,
        name="Complaint",
        category="Record",
        proceeding=proceeding,
        drive_file_id="f1",
        drive_mapping=record_mapping,
    )
    response = _save(client, matter, {"category_rf1": ""})
    assert response.status_code == 204
    assert not DriveFolderMapping.objects.filter(pk=record_mapping.pk).exists()
    doc = Document.objects.get()
    assert (doc.category, doc.proceeding, doc.drive_mapping) == (
        "Record",
        proceeding,
        None,
    )
    assert _queued == []


def test_clash_with_other_matter_rejected(client, matter, proceeding, tree):
    Matter.objects.create(
        name="Other", status="Open", drive_folder_id="mf2", drive_folder="Other Matter"
    )
    response = _save(client, matter, {"matter_folder": "mf2"})
    assert "already linked to Other" in response.content.decode()
    matter.refresh_from_db()
    assert matter.drive_folder_id == "mf1"


def test_changing_folder_drops_old_mappings(
    client, matter, proceeding, record_mapping, tree
):
    response = _save(client, matter, {"matter_folder": "mf2"})
    assert response.status_code == 204
    matter.refresh_from_db()
    assert matter.drive_folder_id == "mf2"
    assert matter.drive_folder == "Other Matter"
    assert DriveFolderMapping.objects.filter(matter=matter).count() == 0


def test_unlink_clears_everything_keeps_documents(
    client, matter, proceeding, record_mapping, tree
):
    Document.objects.create(
        matter=matter,
        name="Complaint",
        category="Record",
        drive_file_id="f1",
        drive_mapping=record_mapping,
    )
    response = client.post(reverse("case:documents-drive-unlink", args=[matter.id]))
    assert response.status_code == 204
    matter.refresh_from_db()
    assert matter.drive_folder is None and matter.drive_folder_id is None
    assert DriveFolderMapping.objects.count() == 0
    assert Document.objects.count() == 1


def test_documents_tab_button_shows_count(
    client, matter, proceeding, record_mapping, tree
):
    DriveMatterState.objects.create(
        matter=matter, unmapped_folders=[{"id": "cf1", "name": "Corr"}]
    )
    Proceeding.objects.create(matter=matter, nickname="Appeal")
    client.session["documents_selected_matter"] = matter.id
    response = client.get(f"/case/{matter.id}/documents/list/")
    body = response.content.decode()
    assert "Drive Folder" in body
    assert "2 to map" in body


def test_edit_blocks_file_replacement_for_synced(
    client, matter, proceeding, record_mapping, fake_drive
):
    from django.core.files.base import ContentFile

    document = Document.objects.create(
        matter=matter,
        proceeding=proceeding,
        category="Record",
        name="Complaint",
        drive_file_id="f1",
    )
    document.file.save("1.pdf", ContentFile(b"%PDF-original"), save=True)

    response = client.post(
        reverse("case:documents-edit", args=[document.id]),
        {
            "name": "Complaint",
            "category": "Record",
            "importance": 4,
            "ai_context": "auto",
            "file": ContentFile(b"%PDF-replacement", name="new.pdf"),
        },
    )
    assert "synced from Google Drive" in response.content.decode()
    with document.file.open("rb") as fh:
        assert fh.read() == b"%PDF-original"
