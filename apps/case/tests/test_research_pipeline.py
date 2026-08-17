"""The research tab's search pipeline (apps/case/research)."""

import pytest

from apps.case.research import (
    courtlistener as research_cl,
    tasks as research_tasks,
)
from apps.case.research.briefing import RESEARCH_ABSTRACT_SYSTEM, parse_brief
from apps.case.research.jurisdictions import get_court_ids

pytestmark = pytest.mark.django_db

SAMPLE_BRIEF = """\
CASE: Birg v. Emory Healthcare, Ga. Ct. App., June 2026.
POSTURE: Appeal from denial of attorney fees.
VEHICLE: OCGA 9-11-37(a)(4)(A) motion-to-compel expenses.
HOLDING: The court held that "the motion must be granted" before fees attach.
RELEVANCE: Directly answers whether fees survive a mooted motion to compel. The reasoning turns on the statutory text.
CAUTIONS: Slip opinion, not yet reported.
SCOPE: Also discusses appellate jurisdiction.
RELEVANCE VERDICT: HIGH
KEY AUTHORITIES:
- 279 Ga. 326
- 300 Ga. App. 1
"""


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


# --------------------------------------------------------------------------- #
# Brief parsing
# --------------------------------------------------------------------------- #
def test_parse_brief_extracts_verdict_authorities_reason():
    parsed = parse_brief(SAMPLE_BRIEF)
    assert parsed["verdict"] == "high"
    assert parsed["key_authorities"] == ["279 Ga. 326", "300 Ga. App. 1"]
    assert parsed["reason"].startswith("Directly answers")


def test_parse_brief_verdict_case_insensitive_and_moderate():
    parsed = parse_brief("RELEVANCE VERDICT: moderate\nKEY AUTHORITIES:\nnone")
    assert parsed["verdict"] == "medium"
    assert parsed["key_authorities"] == []


def test_parse_brief_missing_verdict_defaults_medium():
    parsed = parse_brief("Some unstructured response.")
    assert parsed["verdict"] == "medium"
    assert parsed["key_authorities"] == []
    assert parsed["reason"] == ""


def test_parse_brief_caps_authorities_and_strips_bullets():
    text = (
        "RELEVANCE VERDICT: LOW\n"
        "KEY AUTHORITIES:\n"
        "1. 1 Ga. 1\n"
        "* 2 Ga. 2\n"
        "- 3 Ga. 3\n"
        "- 4 Ga. 4\n"
    )
    parsed = parse_brief(text)
    assert parsed["verdict"] == "low"
    assert parsed["key_authorities"] == ["1 Ga. 1", "2 Ga. 2", "3 Ga. 3"]


def test_abstract_system_has_parseable_sections():
    assert "RELEVANCE VERDICT:" in RESEARCH_ABSTRACT_SYSTEM
    assert "KEY AUTHORITIES:" in RESEARCH_ABSTRACT_SYSTEM
    assert "VEHICLE:" in RESEARCH_ABSTRACT_SYSTEM
    assert "9-11-37(d)" in RESEARCH_ABSTRACT_SYSTEM


# --------------------------------------------------------------------------- #
# Refiner prompt
# --------------------------------------------------------------------------- #
def test_refiner_prompt_carries_design_and_vehicle_rules(matter, monkeypatch):
    from apps.case.research.models import ResearchQuery

    query = ResearchQuery.objects.create(
        matter=matter, query_text="Can I recover fees after a mooted motion?"
    )
    captured = {}

    def fake_gemini(system, messages, **kwargs):
        captured["system"] = system
        return ('"expenses of the motion" AND compel', 0, 0)

    monkeypatch.setattr(research_tasks, "send_to_gemini", fake_gemini)
    research_tasks._refine_query(query.id)
    assert (
        "ONE NEW CONCEPT" in captured["system"]
        or "concept groups" in captured["system"]
    )
    assert "PROCEDURAL VEHICLE" in captured["system"]
    assert "9-11-37(a)(4)" in captured["system"]
    query.refresh_from_db()
    assert query.structured_query == '"expenses of the motion" AND compel'
