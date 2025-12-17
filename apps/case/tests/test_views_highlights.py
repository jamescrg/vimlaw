import json

import pytest
from pytest_django.asserts import assertTemplateUsed

from apps.case.models import Highlight

pytestmark = pytest.mark.django_db


class TestHighlightsIndex:
    def test_index_requires_login(self, client, matter):
        client.logout()
        response = client.get(f"/case/{matter.id}/highlights/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_index_authenticated(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/highlights/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/highlights/main.html")


class TestHighlightsList:
    def test_list_authenticated(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/highlights/list/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/highlights/list.html")

    def test_list_shows_highlights(self, client_with_matter, highlight):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/highlights/list/")
        assert response.status_code == 200
        assert b"Test Highlight" in response.content


class TestAddHighlight:
    def test_add_highlight(self, client_with_matter, document):
        data = {
            "slug": "New Highlight",
            "text": "Some highlighted text",
            "page_number": "2",
            "paragraph_number": "10",
            "coordinates": json.dumps(
                {"rects": [{"x1": 50, "y1": 50, "x2": 150, "y2": 70}]}
            ),
            "color": "green",
        }
        response = client_with_matter.post(
            f"/case/documents/{document.id}/highlights/add/", data
        )
        assert response.status_code == 200
        result = response.json()
        assert result["slug"] == "New Highlight"
        assert Highlight.objects.filter(slug="New Highlight").exists()

    def test_add_highlight_requires_slug(self, client_with_matter, document):
        data = {
            "slug": "",
            "text": "Some text",
            "page_number": "1",
            "coordinates": "{}",
        }
        response = client_with_matter.post(
            f"/case/documents/{document.id}/highlights/add/", data
        )
        assert response.status_code == 400


class TestEditHighlight:
    def test_edit_get(self, client_with_matter, highlight):
        response = client_with_matter.get(f"/case/highlights/{highlight.id}/edit/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/highlights/edit.html")

    def test_edit_post(self, client_with_matter, highlight):
        data = {
            "slug": "Updated Slug",
            "text": highlight.text,
            "color": "blue",
            "importance": 8,
            "paragraph_number": "7",
        }
        response = client_with_matter.post(
            f"/case/highlights/{highlight.id}/edit/", data
        )
        assert response.status_code == 204
        highlight.refresh_from_db()
        assert highlight.slug == "Updated Slug"
        assert highlight.color == "blue"
        assert highlight.importance == 8

    def test_edit_viewer_context_returns_json(self, client_with_matter, highlight):
        data = {
            "slug": "Updated Slug",
            "text": highlight.text,
            "color": "blue",
            "importance": 5,
            "paragraph_number": "",
        }
        response = client_with_matter.post(
            f"/case/highlights/{highlight.id}/edit/?context=viewer", data
        )
        assert response.status_code == 200
        result = response.json()
        assert result["slug"] == "Updated Slug"


class TestDeleteHighlight:
    def test_delete(self, client_with_matter, highlight):
        hl_id = highlight.id
        response = client_with_matter.post(f"/case/highlights/{hl_id}/delete/")
        assert response.status_code == 200
        assert not Highlight.objects.filter(id=hl_id).exists()

    def test_delete_nonexistent(self, client_with_matter):
        response = client_with_matter.post("/case/highlights/99999/delete/")
        assert response.status_code == 404


class TestHighlightImportance:
    def test_set_importance(self, client_with_matter, highlight):
        response = client_with_matter.get(
            f"/case/highlights/{highlight.id}/importance/9/"
        )
        assert response.status_code == 302
        highlight.refresh_from_db()
        assert highlight.importance == 9


class TestHighlightsFilter:
    def test_filter_get(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/highlights/filter/")
        assert response.status_code == 200

    def test_filter_post(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        data = {"keyword": "test", "order_by": "date"}
        response = client_with_matter.post(
            f"/case/{matter_id}/highlights/filter/", data
        )
        assert response.status_code == 204

    def test_filter_by_document(self, client_with_matter, document):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.post(
            f"/case/{matter_id}/highlights/filter/document/{document.id}/"
        )
        assert response.status_code == 204

    def test_filter_by_document_clear(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.post(
            f"/case/{matter_id}/highlights/filter/document/"
        )
        assert response.status_code == 204

    def test_filter_by_keyword(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.post(
            f"/case/{matter_id}/highlights/filter/keyword/", {"keyword": "test"}
        )
        assert response.status_code == 200

    def test_filter_by_importance(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(
            f"/case/{matter_id}/highlights/filter/importance/5/"
        )
        assert response.status_code == 302

    def test_filter_default(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(
            f"/case/{matter_id}/highlights/filter/default/"
        )
        assert response.status_code == 302


class TestHighlightsSort:
    def test_sort_by_date(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(
            f"/case/{matter_id}/highlights/filter/sort/date/"
        )
        assert response.status_code == 204

    def test_sort_by_slug(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(
            f"/case/{matter_id}/highlights/filter/sort/slug/"
        )
        assert response.status_code == 204

    def test_sort_by_importance(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(
            f"/case/{matter_id}/highlights/filter/sort/importance/"
        )
        assert response.status_code == 204


class TestHighlightLink:
    def test_highlight_link_redirects(self, client_with_matter, highlight):
        response = client_with_matter.get(f"/case/highlights/{highlight.id}/link/")
        assert response.status_code == 302
        assert f"/case/documents/{highlight.document_id}/view/" in response.url


class TestHighlightsForDocument:
    def test_redirects_with_filter(self, client_with_matter, document):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/documents/{document.id}/highlights/")
        assert response.status_code == 302
        session = client_with_matter.session
        filter_key = f"highlights_filter_{matter_id}"
        filter_data = session.get(filter_key, {})
        assert filter_data.get("document") == document.id
