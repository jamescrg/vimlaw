import pytest
from pytest_django.asserts import assertTemplateUsed

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _no_semantic_pass(monkeypatch):
    """Keyword-path tests must not embed queries; TestSemanticMerge
    overrides this with a controlled return."""
    monkeypatch.setattr("apps.case.search.views.semantic_entries", lambda *a, **k: [])


class TestSearchIndex:
    def test_index_requires_login(self, client, matter):
        client.logout()
        response = client.get(f"/case/{matter.id}/search/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_index_authenticated(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/search/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/search/main.html")


class TestSearchList:
    def test_list_authenticated(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/search/list/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/search/list.html")


class TestSearchResults:
    def test_results_authenticated(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/search/results/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/search/results.html")


class TestSearchQuery:
    def test_query_post(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        filter_key = f"search_filter_{matter_id}"
        response = client_with_matter.post(
            f"/case/{matter_id}/search/query/", {"query": "test search"}
        )
        assert response.status_code == 200
        session = client_with_matter.session
        filter_data = session.get(filter_key, {})
        assert filter_data.get("query") == "test search"

    def test_query_empty(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.post(
            f"/case/{matter_id}/search/query/", {"query": ""}
        )
        assert response.status_code == 200


class TestSearchFilter:
    def test_filter_get(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/search/filter/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/search/filter-panel.html")

    def test_filter_post(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        filter_key = f"search_filter_{matter_id}"
        data = {"result_type": "document", "category": "Evidence"}
        response = client_with_matter.post(f"/case/{matter_id}/search/filter/", data)
        assert response.status_code == 204
        session = client_with_matter.session
        filter_data = session.get(filter_key, {})
        assert filter_data.get("result_type") == "document"
        assert filter_data.get("category") == "Evidence"

    def test_filter_removes_empty_values(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        filter_key = f"search_filter_{matter_id}"
        # First set a filter
        client_with_matter.post(
            f"/case/{matter_id}/search/filter/", {"result_type": "document"}
        )
        # Then clear it
        response = client_with_matter.post(
            f"/case/{matter_id}/search/filter/", {"result_type": ""}
        )
        assert response.status_code == 204
        session = client_with_matter.session
        filter_data = session.get(filter_key, {})
        assert "result_type" not in filter_data


class TestSearchFilterType:
    def test_filter_by_document(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        filter_key = f"search_filter_{matter_id}"
        response = client_with_matter.get(
            f"/case/{matter_id}/search/filter/type/document/"
        )
        assert response.status_code == 204
        session = client_with_matter.session
        filter_data = session.get(filter_key, {})
        assert filter_data.get("result_type") == "document"

    def test_filter_by_highlight(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        filter_key = f"search_filter_{matter_id}"
        response = client_with_matter.get(
            f"/case/{matter_id}/search/filter/type/highlight/"
        )
        assert response.status_code == 204
        session = client_with_matter.session
        filter_data = session.get(filter_key, {})
        assert filter_data.get("result_type") == "highlight"

    def test_filter_by_fact(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        filter_key = f"search_filter_{matter_id}"
        response = client_with_matter.get(f"/case/{matter_id}/search/filter/type/fact/")
        assert response.status_code == 204
        session = client_with_matter.session
        filter_data = session.get(filter_key, {})
        assert filter_data.get("result_type") == "fact"

    def test_filter_clear_type(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        filter_key = f"search_filter_{matter_id}"
        # First set a type filter
        client_with_matter.get(f"/case/{matter_id}/search/filter/type/document/")
        # Then clear it
        response = client_with_matter.get(f"/case/{matter_id}/search/filter/type/")
        assert response.status_code == 204
        session = client_with_matter.session
        filter_data = session.get(filter_key, {})
        assert "result_type" not in filter_data


class TestSearchClear:
    def test_clear_filters(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        filter_key = f"search_filter_{matter_id}"
        # First set some filters
        session = client_with_matter.session
        session[filter_key] = {
            "query": "test",
            "result_type": "document",
            "category": "Evidence",
        }
        session.save()

        # Clear all filters
        response = client_with_matter.post(f"/case/{matter_id}/search/clear/")
        assert response.status_code == 204
        session = client_with_matter.session
        filter_data = session.get(filter_key, {})
        assert filter_data == {}


class TestSemanticMerge:
    """Meaning matches from the semantic index join the case search."""

    def _row(self, note, similarity=0.71):
        return {
            "kind": "note",
            "object_id": note.id,
            "text": note.content,
            "similarity": similarity,
            "query": "dog",
        }

    def test_meaning_match_row_rendered(self, client_with_matter, monkeypatch):
        from apps.notes.models import Note

        matter = client_with_matter.matter
        note = Note.objects.create(
            matter=matter, title="Companion animal", content="the canine companion"
        )
        monkeypatch.setattr(
            "apps.case.search.views.semantic_entries",
            lambda queries, m, kinds, limit: [[self._row(note)]],
        )
        client_with_matter.post(f"/case/{matter.id}/search/query/", {"query": "dog"})
        html = client_with_matter.get(
            f"/case/{matter.id}/search/results/"
        ).content.decode()
        assert "Companion animal" in html
        assert "meaning match" in html
        assert "result-semantic" in html
        assert "the canine companion" in html

    def test_keyword_hit_not_duplicated(self, client_with_matter, monkeypatch):
        from watson import search as watson

        from apps.notes.models import Note

        matter = client_with_matter.matter
        note = Note.objects.create(
            matter=matter, title="Dog walk", content="the dog was walked"
        )
        watson.default_search_engine.update_obj_index(note)
        monkeypatch.setattr(
            "apps.case.search.views.semantic_entries",
            lambda queries, m, kinds, limit: [[self._row(note)]],
        )
        client_with_matter.post(f"/case/{matter.id}/search/query/", {"query": "dog"})
        html = client_with_matter.get(
            f"/case/{matter.id}/search/results/"
        ).content.decode()
        assert html.count("Dog walk") == 1
        assert "result-semantic" not in html

    def test_scope_respects_disabled_kinds(self, client_with_matter, monkeypatch):
        matter = client_with_matter.matter
        calls = {}

        def spy(queries, m, kinds, limit):
            calls["kinds"] = kinds
            return []

        monkeypatch.setattr("apps.case.search.views.semantic_entries", spy)
        session = client_with_matter.session
        session[f"search_scopes_{matter.id}"] = ["documents", "facts"]
        session.save()
        client_with_matter.post(f"/case/{matter.id}/search/query/", {"query": "dog"})
        client_with_matter.get(f"/case/{matter.id}/search/results/")
        assert calls["kinds"] == ["document", "fact"]
