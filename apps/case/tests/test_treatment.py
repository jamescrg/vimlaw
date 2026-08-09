"""Negative-treatment check: depth filter, recency walk, full-text reads."""

import json

import pytest

from apps.case.courtlistener import OpinionResult
from apps.case.research import tasks as research_tasks

pytestmark = pytest.mark.django_db


class FakeCL:
    """Scriptable CourtListener + Gemini stand-ins patched into tasks."""

    def __init__(self, forward, opinions, clusters, verdicts):
        self.forward = forward
        self.opinions = opinions
        self.clusters = clusters
        self.verdicts = list(verdicts)
        self.classified = []  # (name, prompt) per Flash call
        self.opinion_fetches = []

    def get_forward_citations(self, opinion_id, limit=5):
        return self.forward[:limit]

    def fetch_opinion(self, opinion_id):
        self.opinion_fetches.append(opinion_id)
        return self.opinions.get(
            opinion_id, OpinionResult(found=False, error="missing")
        )

    def fetch_cluster(self, cluster_id):
        return self.clusters.get(cluster_id, {})

    def send_to_gemini(self, system_context, messages, **kwargs):
        prompt = messages[0]["content"]
        self.classified.append(prompt)
        return json.dumps(self.verdicts.pop(0)), 10, 5


@pytest.fixture
def patch_cl(monkeypatch):
    def _install(fake):
        monkeypatch.setattr(
            research_tasks, "get_forward_citations", fake.get_forward_citations
        )
        monkeypatch.setattr(research_tasks, "fetch_opinion", fake.fetch_opinion)
        monkeypatch.setattr(research_tasks, "fetch_cluster", fake.fetch_cluster)
        monkeypatch.setattr(research_tasks, "send_to_gemini", fake.send_to_gemini)
        return fake

    return _install


CITED = {
    900: {"case_name": "Target v. Case", "sub_opinions": ["https://api/opinions/9000/"]}
}


def _opinion(opinion_id, cluster_id, text):
    return OpinionResult(
        found=True, opinion_id=opinion_id, plain_text=text, cluster_id=cluster_id
    )


def _cluster(name, date_filed):
    return {"case_name": name, "date_filed": date_filed, "sub_opinions": []}


def test_single_citation_citers_are_ignored(patch_cl):
    fake = patch_cl(
        FakeCL(
            forward=[
                {"citing_opinion_id": 1, "depth": 1},
                {"citing_opinion_id": 2, "depth": 1},
            ],
            opinions={},
            clusters=CITED,
            verdicts=[],
        )
    )
    outcome = research_tasks.check_negative_treatment(900, "Target v. Case", "1 Ga. 1")
    assert outcome["checked"] is True
    assert outcome["has_negative_treatment"] is False
    assert "passing citations" in outcome["reason"].lower()
    assert fake.opinion_fetches == []  # nothing read
    assert fake.classified == []  # no Flash calls


def test_reads_most_recent_first_and_full_text(patch_cl):
    long_text = "A" * 10_000 + " DISAPPROVAL-MARKER " + "B" * 5_000
    fake = patch_cl(
        FakeCL(
            forward=[
                {"citing_opinion_id": 11, "depth": 9},  # oldest, heaviest citer
                {"citing_opinion_id": 12, "depth": 3},  # most recent
            ],
            opinions={
                11: _opinion(11, 111, "Old citing opinion text."),
                12: _opinion(12, 112, long_text),
            },
            clusters=CITED
            | {
                111: _cluster("Old v. Citer", "1999-01-01"),
                112: _cluster("New v. Citer", "2024-06-01"),
            },
            verdicts=[
                {"treatment": "neutral", "reason": "mentions it"},
                {"treatment": "neutral", "reason": "mentions it"},
            ],
        )
    )
    outcome = research_tasks.check_negative_treatment(900, "Target v. Case", "1 Ga. 1")
    assert outcome["has_negative_treatment"] is False
    # Recency order: the 2024 citer is classified before the 1999 one, even
    # though the 1999 one has higher depth.
    assert "New v. Citer" in fake.classified[0]
    assert "Old v. Citer" in fake.classified[1]
    # Full text reaches the classifier — content past the old 3k excerpt cap.
    assert "DISAPPROVAL-MARKER" in fake.classified[0]


def test_negative_verdict_reports_citing_case(patch_cl):
    patch_cl(
        FakeCL(
            forward=[{"citing_opinion_id": 21, "depth": 4}],
            opinions={21: _opinion(21, 121, "We overrule Target v. Case.")},
            clusters=CITED | {121: _cluster("Overruler v. Case", "2020-05-05")},
            verdicts=[{"treatment": "negative", "reason": "expressly overruled"}],
        )
    )
    outcome = research_tasks.check_negative_treatment(900, "Target v. Case", "1 Ga. 1")
    assert outcome["has_negative_treatment"] is True
    assert "Overruler v. Case" in outcome["reason"]
    assert "expressly overruled" in outcome["reason"]


def test_good_law_stops_the_walk(patch_cl):
    fake = patch_cl(
        FakeCL(
            forward=[
                {"citing_opinion_id": 31, "depth": 5},
                {"citing_opinion_id": 32, "depth": 4},
                {"citing_opinion_id": 33, "depth": 3},
            ],
            opinions={
                31: _opinion(31, 131, "Recent follows."),
                32: _opinion(32, 132, "Middle text."),
                33: _opinion(33, 133, "Old text."),
            },
            clusters=CITED
            | {
                131: _cluster("Recent v. Follower", "2025-01-01"),
                132: _cluster("Middle v. Case", "2015-01-01"),
                133: _cluster("Old v. Case", "2005-01-01"),
            },
            verdicts=[{"treatment": "good_law", "reason": "applies the rule"}],
        )
    )
    outcome = research_tasks.check_negative_treatment(900, "Target v. Case", "1 Ga. 1")
    assert outcome["has_negative_treatment"] is False
    assert "Recent v. Follower" in outcome["reason"]
    assert "good law" in outcome["reason"]
    # Early stop: only the most recent citer was classified.
    assert len(fake.classified) == 1


def test_read_cap_applies_to_substantial_citers(patch_cl):
    forward = [
        {"citing_opinion_id": 40 + i, "depth": 10 - i}
        for i in range(8)  # 8 substantial citers, cap is 5
    ]
    opinions = {
        40 + i: _opinion(40 + i, 140 + i, f"Citing text {i}.") for i in range(8)
    }
    clusters = CITED | {
        140 + i: _cluster(f"Citer {i} v. Case", f"20{10 + i}-01-01") for i in range(8)
    }
    fake = patch_cl(
        FakeCL(
            forward=forward,
            opinions=opinions,
            clusters=clusters,
            verdicts=[{"treatment": "neutral", "reason": "n"}] * 5,
        )
    )
    outcome = research_tasks.check_negative_treatment(900, "Target v. Case", "1 Ga. 1")
    assert outcome["has_negative_treatment"] is False
    assert len(fake.opinion_fetches) == research_tasks.TREATMENT_MAX_READS
    assert len(fake.classified) == research_tasks.TREATMENT_MAX_READS
