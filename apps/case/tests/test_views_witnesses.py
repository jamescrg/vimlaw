"""Tests for witness multi-select and bulk actions."""

import pytest

from apps.case.models import Witness

pytestmark = pytest.mark.django_db


@pytest.fixture
def witness(user, matter):
    return Witness.objects.create(
        user=user,
        matter=matter,
        name="Dr. Alice Reed",
        affiliation="Plaintiff",
        alignment="friendly",
        knowledge="Treated the plaintiff",
    )


@pytest.fixture
def other_witness(user, matter):
    return Witness.objects.create(
        user=user,
        matter=matter,
        name="Bob Smith",
        alignment="hostile",
    )


class TestWitnessSelection:
    def test_toggle_select(self, client_with_matter, witness):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.post(
            f"/case/{matter_id}/witnesses/toggle-select/{witness.id}/"
        )
        assert response.status_code == 204
        assert response.headers["HX-Trigger"] == "witnessesChanged"
        assert client_with_matter.session[f"selected_witnesses_{matter_id}"] == [
            witness.id
        ]

        client_with_matter.post(
            f"/case/{matter_id}/witnesses/toggle-select/{witness.id}/"
        )
        assert client_with_matter.session[f"selected_witnesses_{matter_id}"] == []

    def test_toggle_select_scopes_to_matter(self, client_with_matter, witness, contact):
        from apps.matters.models import Matter

        other = Matter.objects.create(name="Other Matter", client=contact)
        response = client_with_matter.post(
            f"/case/{other.id}/witnesses/toggle-select/{witness.id}/"
        )
        assert response.status_code == 404

    def test_select_all_and_clear(self, client_with_matter, witness, other_witness):
        matter_id = client_with_matter.matter.id
        client_with_matter.post(f"/case/{matter_id}/witnesses/select-all/")
        assert sorted(
            client_with_matter.session[f"selected_witnesses_{matter_id}"]
        ) == sorted([witness.id, other_witness.id])

        client_with_matter.post(f"/case/{matter_id}/witnesses/select-all/")
        assert client_with_matter.session[f"selected_witnesses_{matter_id}"] == []

        client_with_matter.post(
            f"/case/{matter_id}/witnesses/toggle-select/{witness.id}/"
        )
        client_with_matter.post(f"/case/{matter_id}/witnesses/clear-selection/")
        assert client_with_matter.session[f"selected_witnesses_{matter_id}"] == []

    def test_list_shows_bulk_toolbar_when_selected(self, client_with_matter, witness):
        matter_id = client_with_matter.matter.id
        client_with_matter.post(
            f"/case/{matter_id}/witnesses/toggle-select/{witness.id}/"
        )
        response = client_with_matter.get(f"/case/{matter_id}/witnesses/list/")
        assert b"bulk-clear-icon" in response.content
        assert b"bulk-alignment" in response.content
        assert b"bulk-affiliation" in response.content

    def test_single_delete_prunes_selection(self, client_with_matter, witness):
        matter_id = client_with_matter.matter.id
        client_with_matter.post(
            f"/case/{matter_id}/witnesses/toggle-select/{witness.id}/"
        )
        client_with_matter.post(f"/case/witnesses/{witness.id}/delete/")
        assert client_with_matter.session[f"selected_witnesses_{matter_id}"] == []


class TestWitnessBulkActions:
    def _select(self, client, matter_id, *witnesses):
        for witness in witnesses:
            client.post(f"/case/{matter_id}/witnesses/toggle-select/{witness.id}/")

    def test_bulk_requires_selection(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        for path in (
            "bulk-delete",
            "bulk-importance",
            "bulk-alignment",
            "bulk-affiliation",
        ):
            response = client_with_matter.post(f"/case/{matter_id}/witnesses/{path}/")
            assert response.status_code == 400

    def test_bulk_delete(self, client_with_matter, witness, other_witness):
        matter_id = client_with_matter.matter.id
        self._select(client_with_matter, matter_id, witness, other_witness)
        response = client_with_matter.post(f"/case/{matter_id}/witnesses/bulk-delete/")
        assert response.status_code == 204
        assert Witness.objects.count() == 0
        assert client_with_matter.session[f"selected_witnesses_{matter_id}"] == []

    def test_bulk_importance(self, client_with_matter, witness):
        matter_id = client_with_matter.matter.id
        self._select(client_with_matter, matter_id, witness)
        response = client_with_matter.post(
            f"/case/{matter_id}/witnesses/bulk-importance/", {"importance": "6"}
        )
        assert response.status_code == 204
        witness.refresh_from_db()
        assert witness.importance == 6
        assert client_with_matter.session[f"selected_witnesses_{matter_id}"] == []

    def test_bulk_alignment(self, client_with_matter, witness, other_witness):
        matter_id = client_with_matter.matter.id
        self._select(client_with_matter, matter_id, witness, other_witness)
        response = client_with_matter.post(
            f"/case/{matter_id}/witnesses/bulk-alignment/", {"alignment": "hostile"}
        )
        assert response.status_code == 204
        witness.refresh_from_db()
        other_witness.refresh_from_db()
        assert witness.alignment == "hostile"
        assert other_witness.alignment == "hostile"

    def test_bulk_alignment_rejects_invalid(self, client_with_matter, witness):
        matter_id = client_with_matter.matter.id
        self._select(client_with_matter, matter_id, witness)
        response = client_with_matter.post(
            f"/case/{matter_id}/witnesses/bulk-alignment/", {"alignment": "adversarial"}
        )
        assert response.status_code == 400
        witness.refresh_from_db()
        assert witness.alignment == "friendly"

    def test_bulk_affiliation_modal_offers_existing(
        self, client_with_matter, witness, other_witness
    ):
        matter_id = client_with_matter.matter.id
        self._select(client_with_matter, matter_id, other_witness)
        response = client_with_matter.get(
            f"/case/{matter_id}/witnesses/bulk-affiliation/"
        )
        assert response.status_code == 200
        assert b"Plaintiff" in response.content  # existing faction in the datalist

    def test_bulk_affiliation_set_and_clear(
        self, client_with_matter, witness, other_witness
    ):
        matter_id = client_with_matter.matter.id
        self._select(client_with_matter, matter_id, witness, other_witness)
        response = client_with_matter.post(
            f"/case/{matter_id}/witnesses/bulk-affiliation/",
            {"affiliation": "Defendant Acme Corp."},
        )
        assert response.status_code == 204
        witness.refresh_from_db()
        other_witness.refresh_from_db()
        assert witness.affiliation == "Defendant Acme Corp."
        assert other_witness.affiliation == "Defendant Acme Corp."
        assert client_with_matter.session[f"selected_witnesses_{matter_id}"] == []

        self._select(client_with_matter, matter_id, witness)
        response = client_with_matter.post(
            f"/case/{matter_id}/witnesses/bulk-affiliation/", {"affiliation": ""}
        )
        assert response.status_code == 204
        witness.refresh_from_db()
        assert witness.affiliation == ""
