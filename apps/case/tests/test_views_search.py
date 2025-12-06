import pytest
from pytest_django.asserts import assertTemplateUsed

pytestmark = pytest.mark.django_db


class TestSearchIndex:
    def test_index_requires_login(self, client):
        client.logout()
        response = client.get("/case/search/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_index_authenticated(self, client_with_matter):
        response = client_with_matter.get("/case/search/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/search/main.html")


class TestSearchList:
    def test_list_authenticated(self, client_with_matter):
        response = client_with_matter.get("/case/search/list/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/search/list.html")


class TestSearchResults:
    def test_results_authenticated(self, client_with_matter):
        response = client_with_matter.get("/case/search/results/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/search/results.html")


class TestSearchQuery:
    def test_query_post(self, client_with_matter):
        response = client_with_matter.post(
            "/case/search/query/", {"query": "test search"}
        )
        assert response.status_code == 200
        session = client_with_matter.session
        filter_data = session.get("search_filter", {})
        assert filter_data.get("query") == "test search"

    def test_query_empty(self, client_with_matter):
        response = client_with_matter.post("/case/search/query/", {"query": ""})
        assert response.status_code == 200


class TestSearchFilter:
    def test_filter_get(self, client_with_matter):
        response = client_with_matter.get("/case/search/filter/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/search/filter-panel.html")

    def test_filter_post(self, client_with_matter):
        data = {"result_type": "document", "category": "Evidence"}
        response = client_with_matter.post("/case/search/filter/", data)
        assert response.status_code == 204
        session = client_with_matter.session
        filter_data = session.get("search_filter", {})
        assert filter_data.get("result_type") == "document"
        assert filter_data.get("category") == "Evidence"

    def test_filter_removes_empty_values(self, client_with_matter):
        # First set a filter
        client_with_matter.post("/case/search/filter/", {"result_type": "document"})
        # Then clear it
        response = client_with_matter.post("/case/search/filter/", {"result_type": ""})
        assert response.status_code == 204
        session = client_with_matter.session
        filter_data = session.get("search_filter", {})
        assert "result_type" not in filter_data


class TestSearchFilterType:
    def test_filter_by_document(self, client_with_matter):
        response = client_with_matter.get("/case/search/filter/type/document/")
        assert response.status_code == 204
        session = client_with_matter.session
        filter_data = session.get("search_filter", {})
        assert filter_data.get("result_type") == "document"

    def test_filter_by_highlight(self, client_with_matter):
        response = client_with_matter.get("/case/search/filter/type/highlight/")
        assert response.status_code == 204
        session = client_with_matter.session
        filter_data = session.get("search_filter", {})
        assert filter_data.get("result_type") == "highlight"

    def test_filter_by_fact(self, client_with_matter):
        response = client_with_matter.get("/case/search/filter/type/fact/")
        assert response.status_code == 204
        session = client_with_matter.session
        filter_data = session.get("search_filter", {})
        assert filter_data.get("result_type") == "fact"

    def test_filter_clear_type(self, client_with_matter):
        # First set a type filter
        client_with_matter.get("/case/search/filter/type/document/")
        # Then clear it
        response = client_with_matter.get("/case/search/filter/type/")
        assert response.status_code == 204
        session = client_with_matter.session
        filter_data = session.get("search_filter", {})
        assert "result_type" not in filter_data


class TestSearchClear:
    def test_clear_filters(self, client_with_matter):
        # First set some filters
        session = client_with_matter.session
        session["search_filter"] = {
            "query": "test",
            "result_type": "document",
            "category": "Evidence",
        }
        session.save()

        # Clear all filters
        response = client_with_matter.post("/case/search/clear/")
        assert response.status_code == 204
        session = client_with_matter.session
        filter_data = session.get("search_filter", {})
        assert filter_data == {}
