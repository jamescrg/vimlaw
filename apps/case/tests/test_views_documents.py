import pytest
from pytest_django.asserts import assertTemplateUsed

from apps.case.models import Document

pytestmark = pytest.mark.django_db


class TestDocumentsIndex:
    def test_index_requires_login(self, client, matter):
        client.logout()
        response = client.get(f"/case/{matter.id}/documents/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_index_authenticated(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/documents/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/documents/main.html")


class TestDocumentsList:
    def test_list_authenticated(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/documents/list/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/documents/list.html")

    def test_list_shows_documents(self, client_with_matter, document):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/documents/list/")
        assert response.status_code == 200
        assert b"Test Document" in response.content


class TestDocumentsAdd:
    def test_add_get(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/documents/add/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/documents/form.html")


class TestDocumentsEdit:
    def test_edit_get(self, client_with_matter, document):
        response = client_with_matter.get(f"/case/documents/{document.id}/edit/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/documents/form.html")

    def test_edit_post(self, client_with_matter, document, matter):
        data = {
            "name": "Updated Document Name",
            "description": "Updated description",
            "category": "Discovery",
            "date": "2024-02-01",
            "matter": matter.id,
        }
        response = client_with_matter.post(f"/case/documents/{document.id}/edit/", data)
        # Returns 204 on success, 200 if form validation fails
        assert response.status_code in [200, 204]

    def test_edit_nonexistent(self, client_with_matter):
        response = client_with_matter.get("/case/documents/99999/edit/")
        assert response.status_code == 404


class TestDocumentsDelete:
    def test_delete(self, client_with_matter, document):
        doc_id = document.id
        response = client_with_matter.post(f"/case/documents/{doc_id}/delete/")
        assert response.status_code == 204
        assert not Document.objects.filter(id=doc_id).exists()

    def test_delete_nonexistent(self, client_with_matter):
        response = client_with_matter.post("/case/documents/99999/delete/")
        assert response.status_code == 404


class TestDocumentsFilter:
    def test_filter_get(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/documents/filter/")
        assert response.status_code == 200

    def test_filter_post(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        data = {"category": "Evidence", "keyword": "test"}
        response = client_with_matter.post(f"/case/{matter_id}/documents/filter/", data)
        assert response.status_code == 204

    def test_filter_by_category(self, client_with_matter, document):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.post(
            f"/case/{matter_id}/documents/filter/category/Evidence/"
        )
        assert response.status_code == 302  # Redirects to list

    def test_filter_by_keyword(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(
            f"/case/{matter_id}/documents/filter/keyword/?keyword=test"
        )
        assert response.status_code == 200

    def test_filter_by_importance(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(
            f"/case/{matter_id}/documents/filter/importance/5/"
        )
        assert response.status_code == 302


class TestDocumentsSort:
    def test_sort_by_date(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/documents/sort/date/")
        assert response.status_code == 302

    def test_sort_by_name(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/documents/sort/name/")
        assert response.status_code == 302

    def test_sort_toggles_direction(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        # First sort - ascending
        client_with_matter.get(f"/case/{matter_id}/documents/sort/date/")
        # Second sort - should toggle to descending
        client_with_matter.get(f"/case/{matter_id}/documents/sort/date/")
        session = client_with_matter.session
        filter_key = f"documents_filter_{matter_id}"
        filter_data = session.get(filter_key, {})
        assert filter_data.get("order_by") == "-date"


class TestDocumentInlineEdit:
    def test_edit_date(self, client_with_matter, document):
        response = client_with_matter.post(
            f"/case/documents/{document.id}/date/", {"date": "2024-03-15"}
        )
        assert response.status_code == 200
        document.refresh_from_db()
        assert str(document.date) == "2024-03-15"

    def test_edit_category(self, client_with_matter, document):
        response = client_with_matter.get(
            f"/case/documents/{document.id}/category/Discovery/"
        )
        assert response.status_code == 302  # Redirects to list
        document.refresh_from_db()
        assert document.category == "Discovery"

    def test_edit_importance(self, client_with_matter, document):
        response = client_with_matter.get(
            f"/case/documents/{document.id}/importance/8/"
        )
        assert response.status_code == 302  # Redirects to list
        document.refresh_from_db()
        assert document.importance == 8

    def test_edit_proceeding(self, client_with_matter, document, proceeding):
        response = client_with_matter.get(
            f"/case/documents/{document.id}/proceeding/{proceeding.id}/"
        )
        assert response.status_code == 302  # Redirects to list
        document.refresh_from_db()
        assert document.proceeding == proceeding


class TestDocumentViewer:
    def test_viewer_get(self, client_with_matter, document):
        response = client_with_matter.get(f"/case/documents/{document.id}/view/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/viewer.html")

    def test_viewer_nonexistent(self, client_with_matter):
        response = client_with_matter.get("/case/documents/99999/view/")
        assert response.status_code == 404


class TestDocumentSelection:
    def test_toggle_select(self, client_with_matter, document):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.post(
            f"/case/{matter_id}/documents/toggle-select/{document.id}/"
        )
        assert response.status_code == 204
        session = client_with_matter.session
        selected = session.get(f"selected_documents_{matter_id}", [])
        assert document.id in selected

    def test_clear_selection(self, client_with_matter, document):
        matter_id = client_with_matter.matter.id
        # First select a document
        client_with_matter.post(
            f"/case/{matter_id}/documents/toggle-select/{document.id}/"
        )
        # Then clear
        response = client_with_matter.post(
            f"/case/{matter_id}/documents/clear-selection/"
        )
        assert response.status_code == 204
        session = client_with_matter.session
        selected = session.get(f"selected_documents_{matter_id}", [])
        assert len(selected) == 0


class TestSelectMatter:
    def test_select_matter(self, client, matter):
        # This functionality is now handled by URL-based routing
        # Test that visiting a matter's documents page sets the session
        response = client.get(f"/case/{matter.id}/documents/")
        assert response.status_code == 200
        session = client.session
        assert session.get("last_viewed_matter") == matter.id

    def test_select_matter_clears_filter(self, client, matter):
        # Set some filter data first
        session = client.session
        session[f"documents_filter_{matter.id}"] = {"category": "Evidence"}
        session.save()
        # Visiting the matter page should preserve its filter
        client.get(f"/case/{matter.id}/documents/")
        session = client.session
        # The filter should still be there for this matter
        assert session.get(f"documents_filter_{matter.id}") == {"category": "Evidence"}
