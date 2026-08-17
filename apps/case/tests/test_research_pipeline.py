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
# Full-opinion briefing pipeline
# --------------------------------------------------------------------------- #
HIGH_BRIEF = SAMPLE_BRIEF

LOW_BRIEF = (
    "CASE: Off Point v. Case.\n"
    "RELEVANCE: Concerns an unrelated venue dispute.\n"
    "RELEVANCE VERDICT: LOW\n"
    "KEY AUTHORITIES:\nnone\n"
)


class FakePipelineCL:
    """Scriptable CL + Gemini stand-ins that dispatch on prompt content,
    so ThreadPoolExecutor ordering can't break the script."""

    def __init__(
        self, search_results, clusters, opinions, reject_names=(), low_names=()
    ):
        from apps.case.courtlistener import OpinionResult

        self.search_results = search_results
        self.clusters = clusters
        self.opinions = {
            oid: OpinionResult(found=True, opinion_id=oid, plain_text=text)
            for oid, text in opinions.items()
        }
        self.reject_names = reject_names
        self.low_names = low_names
        self.searches = []
        self.opinion_fetches = []
        self.brief_prompts = []

    def search_opinions(self, query, court="", limit=5, order_by="score desc"):
        self.searches.append(
            {"query": query, "court": court, "limit": limit, "order_by": order_by}
        )
        return list(self.search_results), 200

    def fetch_cluster(self, cluster_id):
        return self.clusters.get(cluster_id, {})

    def fetch_opinion(self, opinion_id):
        from apps.case.courtlistener import OpinionResult

        self.opinion_fetches.append(opinion_id)
        return self.opinions.get(opinion_id, OpinionResult(found=False, error="x"))

    def send_to_gemini(self, system_context, messages, **kwargs):
        import json as _json

        prompt = messages[0]["content"]
        if "triage" in system_context:
            reject = any(name in prompt for name in self.reject_names)
            return (
                _json.dumps({"proceed": not reject, "reason": "Clearly unrelated."}),
                0,
                0,
            )
        if "QUESTION PRESENTED" in prompt:
            self.brief_prompts.append(prompt)
            if any(name in prompt for name in self.low_names):
                return LOW_BRIEF, 0, 0
            return HIGH_BRIEF, 0, 0
        return "Synthesis.", 0, 0


def _row(name, cluster_id, snippet="some snippet"):
    return {
        "case_name": name,
        "citation": [],
        "court": "Supreme Court of Georgia",
        "date_filed": "2026-06-01",
        "cluster_id": cluster_id,
        "snippet": snippet,
        "score": 1.0,
        "cite_count": 0,
        "courtlistener_url": "",
    }


@pytest.fixture
def patch_pipeline(monkeypatch):
    def _install(fake):
        monkeypatch.setattr(research_tasks, "search_opinions", fake.search_opinions)
        monkeypatch.setattr(research_tasks, "fetch_cluster", fake.fetch_cluster)
        monkeypatch.setattr(research_tasks, "fetch_opinion", fake.fetch_opinion)
        monkeypatch.setattr(research_tasks, "send_to_gemini", fake.send_to_gemini)
        monkeypatch.setattr(
            research_tasks, "get_forward_citations", lambda opinion_id, limit=5: []
        )
        return fake

    return _install


def test_get_all_opinion_texts_reads_every_sub_opinion(patch_pipeline):
    fake = patch_pipeline(
        FakePipelineCL(
            [],
            clusters={
                7: {
                    "sub_opinions": [
                        "https://api/opinions/71/",
                        "https://api/opinions/72/",
                    ]
                }
            },
            opinions={71: "MAJORITY TEXT. ", 72: "DISSENT TEXT."},
        )
    )
    text = research_tasks._get_all_opinion_texts(7)
    assert "MAJORITY TEXT" in text
    assert "DISSENT TEXT" in text
    assert "next opinion in this cluster" in text
    assert fake.opinion_fetches == [71, 72]


def test_get_all_opinion_texts_respects_cap(patch_pipeline):
    fake = patch_pipeline(
        FakePipelineCL(
            [],
            clusters={
                7: {
                    "sub_opinions": [
                        "https://api/opinions/71/",
                        "https://api/opinions/72/",
                    ]
                }
            },
            opinions={71: "A" * 500, 72: "B" * 500},
        )
    )
    text = research_tasks._get_all_opinion_texts(7, cap=100)
    assert len(text) == 100
    assert fake.opinion_fetches == [71]


@pytest.mark.django_db(transaction=True)
def test_pipeline_keeps_rejected_and_low_rows(matter, user, patch_pipeline):
    """End-to-end _process_query run. transaction=True because the briefing
    ThreadPoolExecutor's threads write on their own DB connections, which
    can't see rows still inside a test transaction."""
    from apps.case.research.models import ResearchQuery, ResearchResult

    fake = patch_pipeline(
        FakePipelineCL(
            [_row("Case One", 1), _row("Case Two", 2), _row("Case Three", 3)],
            clusters={
                cid: {"sub_opinions": [f"https://api/opinions/{cid}0/"]}
                for cid in (1, 2, 3)
            },
            opinions={10: "Opinion one.", 20: "Opinion two.", 30: "Opinion three."},
            reject_names=("Case Two",),
            low_names=("Case Three",),
        )
    )
    query = ResearchQuery.objects.create(
        matter=matter, query_text="fees after mooted motion", created_by=user
    )
    research_tasks._process_query(query.id)

    rows = {r.case_name: r for r in ResearchResult.objects.filter(query=query)}
    assert len(rows) == 3  # nothing deleted

    assert rows["Case Two"].relevance == "rejected"
    assert rows["Case Two"].eval_reason == "Clearly unrelated."
    assert rows["Case Three"].relevance == "low"
    assert rows["Case One"].relevance == "high"
    assert rows["Case One"].brief.startswith("CASE: Birg")
    assert rows["Case One"].key_authorities == ["279 Ga. 326", "300 Ga. App. 1"]
    assert rows["Case One"].eval_reason.startswith("Directly answers")

    # Ruled-out rows sink to the end.
    ordered = list(ResearchResult.objects.filter(query=query).order_by("position"))
    assert [r.case_name for r in ordered] == ["Case One", "Case Two", "Case Three"] or [
        r.case_name for r in ordered
    ] == ["Case One", "Case Three", "Case Two"]
    assert ordered[0].case_name == "Case One"

    # The rejected case was never fetched or briefed.
    assert all("Case Two" not in p for p in fake.brief_prompts)


def test_results_view_splits_ruled_out(client, matter, user):
    from django.urls import reverse as dj_reverse

    from apps.case.research.models import ResearchQuery, ResearchResult

    query = ResearchQuery.objects.create(
        matter=matter, query_text="q", status="complete", created_by=user
    )
    ResearchResult.objects.create(
        query=query, position=1, case_name="Keeper", relevance="high", cluster_id=1
    )
    ResearchResult.objects.create(
        query=query,
        position=2,
        case_name="Dropped",
        relevance="rejected",
        eval_reason="Unrelated to the issue.",
        cluster_id=2,
    )
    url = dj_reverse("case:research-results", args=[matter.id, query.id])
    html = client.get(url).content.decode()
    assert "Ruled out (1)" in html
    assert "Unrelated to the issue." in html
    assert "Keeper" in html


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
