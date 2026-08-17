"""The research tab's search pipeline (apps/case/research)."""

import pytest

from apps.case.research import courtlistener as research_cl
from apps.case.research.jurisdictions import get_court_ids

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- #
# Jurisdictions
# --------------------------------------------------------------------------- #
def test_court_ids_state_only_unchanged():
    assert get_court_ids("ga") == "ga gactapp"
    assert get_court_ids("ga", include_federal=False) == "ga gactapp"


def test_court_ids_federal_adds_districts_circuit_scotus():
    courts = get_court_ids("ga", include_federal=True).split()
    assert courts == ["ga", "gactapp", "gand", "gamd", "gasd", "ca11", "scotus"]


def test_court_ids_federal_without_district_list():
    """States without a district list still get circuit + SCOTUS."""
    courts = get_court_ids("alaska", include_federal=True).split()
    assert courts == ["alaska", "alaskactapp", "ca9", "scotus"]


def test_court_ids_unknown_state_empty():
    assert get_court_ids("") == ""
    assert get_court_ids("narnia", include_federal=True) == ""


# --------------------------------------------------------------------------- #
# search_opinions order_by
# --------------------------------------------------------------------------- #
def _capture_search(monkeypatch):
    captured = {}

    class Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"results": []}

    def fake_request(method, url, headers=None, params=None, timeout=None):
        captured.update(params or {})
        return Resp()

    monkeypatch.setattr(research_cl, "throttled_request", fake_request)
    monkeypatch.setattr(research_cl, "get_api_token", lambda: "token")
    return captured


def test_search_defaults_to_relevance_order(monkeypatch):
    captured = _capture_search(monkeypatch)
    research_cl.search_opinions("partition", limit=20)
    assert captured["order_by"] == "score desc"
    assert captured["page_size"] == 20


def test_search_accepts_date_order(monkeypatch):
    captured = _capture_search(monkeypatch)
    research_cl.search_opinions("partition", limit=10, order_by="dateFiled desc")
    assert captured["order_by"] == "dateFiled desc"
