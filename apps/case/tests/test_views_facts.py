import pytest
from pytest_django.asserts import assertTemplateUsed

from apps.case.models import Fact

pytestmark = pytest.mark.django_db


class TestFactsIndex:
    def test_index_requires_login(self, client):
        client.logout()
        response = client.get("/case/facts/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_index_authenticated(self, client_with_matter):
        response = client_with_matter.get("/case/facts/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/facts/main.html")


class TestFactsList:
    def test_list_authenticated(self, client_with_matter):
        response = client_with_matter.get("/case/facts/list/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/facts/list.html")

    def test_list_shows_facts(self, client_with_matter, fact):
        response = client_with_matter.get("/case/facts/list/")
        assert response.status_code == 200
        assert b"Important event occurred" in response.content


class TestFactsAdd:
    def test_add_get(self, client_with_matter):
        response = client_with_matter.get("/case/facts/add/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/facts/form.html")

    def test_add_post(self, client_with_matter):
        data = {
            "date": "2024-02-15",
            "description": "New fact added",
            "importance": 7,
        }
        response = client_with_matter.post("/case/facts/add/", data)
        assert response.status_code == 204
        assert Fact.objects.filter(description="New fact added").exists()

    def test_add_requires_matter(self, client):
        # Without matter selected
        data = {"date": "2024-02-15", "description": "Test"}
        response = client.post("/case/facts/add/", data)
        assert response.status_code == 400


class TestFactsEdit:
    def test_edit_get(self, client_with_matter, fact):
        response = client_with_matter.get(f"/case/facts/{fact.id}/edit/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/facts/form.html")

    def test_edit_post(self, client_with_matter, fact):
        data = {
            "date": "2024-02-20",
            "description": "Updated fact description",
            "importance": 8,
        }
        response = client_with_matter.post(f"/case/facts/{fact.id}/edit/", data)
        assert response.status_code == 204
        fact.refresh_from_db()
        assert fact.description == "Updated fact description"
        assert fact.importance == 8

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
        response = client_with_matter.get("/case/facts/filter/")
        assert response.status_code == 200

    def test_filter_post(self, client_with_matter):
        data = {"keyword": "test", "order_by": "date"}
        response = client_with_matter.post("/case/facts/filter/", data)
        assert response.status_code == 204

    def test_filter_by_keyword(self, client_with_matter):
        response = client_with_matter.get("/case/facts/filter/keyword/?keyword=event")
        assert response.status_code == 200

    def test_filter_by_importance(self, client_with_matter):
        response = client_with_matter.get("/case/facts/filter/importance/5/")
        assert response.status_code == 302


class TestFactsSort:
    def test_sort_by_date(self, client_with_matter):
        response = client_with_matter.get("/case/facts/sort/date/")
        assert response.status_code == 302

    def test_sort_toggles_direction(self, client_with_matter):
        # First sort - ascending
        client_with_matter.get("/case/facts/sort/date/")
        session = client_with_matter.session
        filter_data = session.get("facts_filter", {})
        assert filter_data.get("order_by") == "date"

        # Second sort - should toggle to descending
        client_with_matter.get("/case/facts/sort/date/")
        session = client_with_matter.session
        filter_data = session.get("facts_filter", {})
        assert filter_data.get("order_by") == "-date"


class TestFactImportance:
    def test_set_importance(self, client_with_matter, fact):
        response = client_with_matter.get(f"/case/facts/{fact.id}/importance/9/")
        assert response.status_code == 302
        fact.refresh_from_db()
        assert fact.importance == 9


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
        response = client_with_matter.get("/case/facts/print/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/facts/print.html")
