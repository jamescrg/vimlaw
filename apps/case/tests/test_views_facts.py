import pytest
from pytest_django.asserts import assertTemplateUsed

from apps.case.models import Fact

pytestmark = pytest.mark.django_db


class TestFactsIndex:
    def test_index_requires_login(self, client, matter):
        client.logout()
        response = client.get(f"/case/{matter.id}/facts/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_index_authenticated(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/facts/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/facts/main.html")


class TestFactsList:
    def test_list_authenticated(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/facts/list/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/facts/list.html")

    def test_list_shows_facts(self, client_with_matter, fact):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/facts/list/")
        assert response.status_code == 200
        assert b"Important event occurred" in response.content


class TestFactsAdd:
    def test_add_get(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/facts/add/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/facts/form.html")

    def test_add_post(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        data = {
            "date": "2024-02-15",
            "description": "New fact added",
            "importance": 4,
        }
        response = client_with_matter.post(f"/case/{matter_id}/facts/add/", data)
        assert response.status_code == 204
        assert Fact.objects.filter(description="New fact added").exists()

    def test_add_requires_matter(self, client, matter):
        # With valid matter_id in URL, the fact should be created
        data = {"date": "2024-02-15", "description": "Test fact", "importance": 5}
        response = client.post(f"/case/{matter.id}/facts/add/", data)
        # Should succeed with valid matter_id in URL
        assert response.status_code == 204
        assert Fact.objects.filter(description="Test fact").exists()


class TestFactsEdit:
    def test_edit_get(self, client_with_matter, fact):
        response = client_with_matter.get(f"/case/facts/{fact.id}/edit/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/facts/form.html")

    def test_edit_post(self, client_with_matter, fact):
        data = {
            "date": "2024-02-20",
            "description": "Updated fact description",
            "importance": 4,
        }
        response = client_with_matter.post(f"/case/facts/{fact.id}/edit/", data)
        assert response.status_code == 204
        fact.refresh_from_db()
        assert fact.description == "Updated fact description"
        assert fact.importance == 4

    def test_edit_nonexistent(self, client_with_matter):
        response = client_with_matter.get("/case/facts/99999/edit/")
        assert response.status_code == 404


class TestFactsDelete:
    def test_delete(self, client_with_matter, fact):
        fact_id = fact.id
        response = client_with_matter.post(f"/case/facts/{fact_id}/delete/")
        assert response.status_code == 204
        assert not Fact.objects.filter(id=fact_id).exists()

    def test_delete_nonexistent(self, client_with_matter):
        response = client_with_matter.post("/case/facts/99999/delete/")
        assert response.status_code == 404


class TestFactsFilter:
    def test_filter_get(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/facts/filter/")
        assert response.status_code == 200

    def test_filter_post(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        data = {"keyword": "test", "order_by": "date"}
        response = client_with_matter.post(f"/case/{matter_id}/facts/filter/", data)
        assert response.status_code == 204

    def test_filter_by_keyword(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(
            f"/case/{matter_id}/facts/filter/keyword/?keyword=event"
        )
        assert response.status_code == 200

    def test_filter_by_importance(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(
            f"/case/{matter_id}/facts/filter/importance/5/"
        )
        assert response.status_code == 302


class TestFactsSort:
    def test_sort_by_date(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/facts/sort/date/")
        assert response.status_code == 302

    def test_sort_toggles_direction(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        filter_key = f"facts_filter_{matter_id}"

        # First sort - ascending
        client_with_matter.get(f"/case/{matter_id}/facts/sort/date/")
        session = client_with_matter.session
        filter_data = session.get(filter_key, {})
        assert filter_data.get("order_by") == "date"

        # Second sort - should toggle to descending
        client_with_matter.get(f"/case/{matter_id}/facts/sort/date/")
        session = client_with_matter.session
        filter_data = session.get(filter_key, {})
        assert filter_data.get("order_by") == "-date"


class TestFactImportance:
    def test_set_importance(self, client_with_matter, fact):
        response = client_with_matter.get(f"/case/facts/{fact.id}/importance/4/")
        assert response.status_code == 302
        fact.refresh_from_db()
        assert fact.importance == 4


class TestFactInlineEdit:
    def test_edit_description_get(self, client_with_matter, fact):
        response = client_with_matter.get(f"/case/facts/{fact.id}/edit-description/")
        assert response.status_code == 200

    def test_update_description(self, client_with_matter, fact):
        response = client_with_matter.post(
            f"/case/facts/{fact.id}/update-description/",
            {"description": "Inline updated"},
        )
        assert response.status_code == 200
        fact.refresh_from_db()
        assert fact.description == "Inline updated"


class TestFactSources:
    def test_sources_modal(self, client_with_matter, fact):
        response = client_with_matter.get(f"/case/facts/{fact.id}/sources/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/facts/sources-modal.html")

    def test_sources_search(self, client_with_matter, fact):
        response = client_with_matter.get(
            f"/case/facts/{fact.id}/sources/search/?q=test"
        )
        assert response.status_code == 200

    def test_add_document_source(self, client_with_matter, fact, document):
        response = client_with_matter.post(
            f"/case/facts/{fact.id}/sources/add/",
            {"type": "document", "id": document.id},
        )
        assert response.status_code == 200
        assert document in fact.documents.all()

    def test_add_highlight_source(self, client_with_matter, fact, highlight):
        response = client_with_matter.post(
            f"/case/facts/{fact.id}/sources/add/",
            {"type": "highlight", "id": highlight.id},
        )
        assert response.status_code == 200
        assert highlight in fact.highlights.all()

    def test_remove_document_source(self, client_with_matter, fact, document):
        fact.documents.add(document)
        response = client_with_matter.post(
            f"/case/facts/{fact.id}/sources/remove/",
            {"type": "document", "id": document.id},
        )
        assert response.status_code == 200
        assert document not in fact.documents.all()

    def test_remove_highlight_source(self, client_with_matter, fact, highlight):
        fact.highlights.add(highlight)
        response = client_with_matter.post(
            f"/case/facts/{fact.id}/sources/remove/",
            {"type": "highlight", "id": highlight.id},
        )
        assert response.status_code == 200
        assert highlight not in fact.highlights.all()


class TestFactsPrint:
    def test_print_view(self, client_with_matter, fact):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/facts/print/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/facts/print.html")


class TestFactsSelection:
    def test_toggle_select(self, client_with_matter, fact):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.post(
            f"/case/{matter_id}/facts/toggle-select/{fact.id}/"
        )
        assert response.status_code == 204
        assert response.headers["HX-Trigger"] == "factsChanged"
        assert client_with_matter.session[f"selected_facts_{matter_id}"] == [fact.id]

        # Toggling again deselects
        client_with_matter.post(f"/case/{matter_id}/facts/toggle-select/{fact.id}/")
        assert client_with_matter.session[f"selected_facts_{matter_id}"] == []

    def test_toggle_select_scopes_to_matter(self, client_with_matter, fact, contact):
        from apps.matters.models import Matter

        other = Matter.objects.create(name="Other Matter", client=contact)
        response = client_with_matter.post(
            f"/case/{other.id}/facts/toggle-select/{fact.id}/"
        )
        assert response.status_code == 404

    def test_select_all_and_clear(self, client_with_matter, fact, user, matter):
        matter_id = client_with_matter.matter.id
        other_fact = Fact.objects.create(
            user=user, matter=matter, date="2024-02-01", description="Second event"
        )
        client_with_matter.post(f"/case/{matter_id}/facts/select-all/")
        assert sorted(client_with_matter.session[f"selected_facts_{matter_id}"]) == [
            fact.id,
            other_fact.id,
        ]

        # Select-all again deselects everything
        client_with_matter.post(f"/case/{matter_id}/facts/select-all/")
        assert client_with_matter.session[f"selected_facts_{matter_id}"] == []

        client_with_matter.post(f"/case/{matter_id}/facts/toggle-select/{fact.id}/")
        client_with_matter.post(f"/case/{matter_id}/facts/clear-selection/")
        assert client_with_matter.session[f"selected_facts_{matter_id}"] == []

    def test_list_shows_bulk_toolbar_when_selected(self, client_with_matter, fact):
        matter_id = client_with_matter.matter.id
        client_with_matter.post(f"/case/{matter_id}/facts/toggle-select/{fact.id}/")
        response = client_with_matter.get(f"/case/{matter_id}/facts/list/")
        assert b"bulk-clear-icon" in response.content
        assert b"bulk-color" in response.content

    def test_single_delete_prunes_selection(self, client_with_matter, fact):
        matter_id = client_with_matter.matter.id
        client_with_matter.post(f"/case/{matter_id}/facts/toggle-select/{fact.id}/")
        client_with_matter.post(f"/case/facts/{fact.id}/delete/")
        assert client_with_matter.session[f"selected_facts_{matter_id}"] == []


class TestFactsBulkActions:
    def _select(self, client, matter_id, *facts):
        for fact in facts:
            client.post(f"/case/{matter_id}/facts/toggle-select/{fact.id}/")

    def test_bulk_requires_selection(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        for path in ("bulk-delete", "bulk-importance", "bulk-color", "bulk-labels"):
            response = client_with_matter.post(f"/case/{matter_id}/facts/{path}/")
            assert response.status_code == 400

    def test_bulk_delete(self, client_with_matter, fact, user, matter):
        matter_id = client_with_matter.matter.id
        other_fact = Fact.objects.create(
            user=user, matter=matter, date="2024-02-01", description="Second event"
        )
        self._select(client_with_matter, matter_id, fact, other_fact)
        response = client_with_matter.post(f"/case/{matter_id}/facts/bulk-delete/")
        assert response.status_code == 204
        assert Fact.objects.count() == 0
        assert client_with_matter.session[f"selected_facts_{matter_id}"] == []

    def test_bulk_importance(self, client_with_matter, fact):
        matter_id = client_with_matter.matter.id
        self._select(client_with_matter, matter_id, fact)
        response = client_with_matter.post(
            f"/case/{matter_id}/facts/bulk-importance/", {"importance": "6"}
        )
        assert response.status_code == 204
        fact.refresh_from_db()
        assert fact.importance == 6
        assert client_with_matter.session[f"selected_facts_{matter_id}"] == []

    def test_bulk_color_set_and_clear(self, client_with_matter, fact):
        matter_id = client_with_matter.matter.id
        self._select(client_with_matter, matter_id, fact)
        response = client_with_matter.post(
            f"/case/{matter_id}/facts/bulk-color/", {"color": "Red"}
        )
        assert response.status_code == 204
        fact.refresh_from_db()
        assert fact.color == "Red"

        self._select(client_with_matter, matter_id, fact)
        response = client_with_matter.post(
            f"/case/{matter_id}/facts/bulk-color/", {"color": ""}
        )
        assert response.status_code == 204
        fact.refresh_from_db()
        assert fact.color is None

    def test_bulk_color_rejects_invalid(self, client_with_matter, fact):
        matter_id = client_with_matter.matter.id
        self._select(client_with_matter, matter_id, fact)
        response = client_with_matter.post(
            f"/case/{matter_id}/facts/bulk-color/", {"color": "Chartreuse"}
        )
        assert response.status_code == 400
        fact.refresh_from_db()
        assert fact.color is None

    def test_bulk_labels_modal_tristate(self, client_with_matter, fact, user, matter):
        from apps.case.models import Label

        matter_id = client_with_matter.matter.id
        other_fact = Fact.objects.create(
            user=user, matter=matter, date="2024-02-01", description="Second event"
        )
        partial = Label.objects.create(matter=matter, name="Key", color="red")
        fact.labels.add(partial)

        self._select(client_with_matter, matter_id, fact, other_fact)
        response = client_with_matter.get(f"/case/{matter_id}/facts/bulk-labels/")
        assert response.status_code == 200
        assert b"state-some" in response.content
        assert b"partial" in response.content

    def test_bulk_label_add_and_remove(self, client_with_matter, fact, user, matter):
        from apps.case.models import Label

        matter_id = client_with_matter.matter.id
        other_fact = Fact.objects.create(
            user=user, matter=matter, date="2024-02-01", description="Second event"
        )
        label = Label.objects.create(matter=matter, name="Key", color="red")

        self._select(client_with_matter, matter_id, fact, other_fact)
        response = client_with_matter.post(
            f"/case/{matter_id}/facts/bulk-label-action/",
            {"label_id": label.id, "action": "add"},
        )
        assert response.status_code == 200
        assert response.headers["HX-Trigger"] == "factsChanged"
        assert label in fact.labels.all()
        assert label in other_fact.labels.all()
        # Selection survives so more labels can be toggled
        assert sorted(
            client_with_matter.session[f"selected_facts_{matter_id}"]
        ) == sorted([fact.id, other_fact.id])

        response = client_with_matter.post(
            f"/case/{matter_id}/facts/bulk-label-action/",
            {"label_id": label.id, "action": "remove"},
        )
        assert response.status_code == 200
        assert fact.labels.count() == 0
        assert other_fact.labels.count() == 0
