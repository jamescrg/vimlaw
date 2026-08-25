"""Tests for AI-saved authorities (save-caselaw fenced blocks)."""

import json

import pytest

from apps.case.ai.caselaw_blocks import (
    CASELAW_TRIGGER_RE,
    apply_caselaw_blocks,
)
from apps.case.models import CaseLaw

pytestmark = pytest.mark.django_db

CLUSTER = {
    "case_name": "Valdosta Hotel Properties, LLC v. White",
    "citations": [{"volume": 278, "reporter": "Ga. App.", "page": "206", "type": 1}],
    "date_filed": "2006-03-17",
    "docket_number": "A05A2117",
    "court": "https://x/api/rest/v4/courts/gactapp/",
    "sub_opinions": ["https://x/api/rest/v4/opinions/9001/"],
    "absolute_url": "/opinion/888/valdosta/",
}


def block(entries):
    return "Answer text.\n\n```save-caselaw\n" + json.dumps(entries) + "\n```"


@pytest.fixture(autouse=True)
def _fake_courtlistener(monkeypatch):
    monkeypatch.setattr(
        "apps.case.courtlistener.fetch_cluster",
        lambda cid: dict(CLUSTER) if cid == 888 else {},
    )
    monkeypatch.setattr(
        "apps.case.research.tasks.generate_caselaw_summary", lambda pk: None
    )


class TestApply:
    def test_creates_caselaw_with_proposition(self, matter, user):
        text = apply_caselaw_blocks(
            block(
                [
                    {
                        "cluster_id": 888,
                        "proposition": "Dropping a party requires a motion and order.",
                        "court": "Georgia Court of Appeals",
                    }
                ]
            ),
            matter,
            user,
        )
        case = CaseLaw.objects.get(matter=matter, cluster_id=888)
        assert case.case_name == "Valdosta Hotel Properties, LLC v. White"
        assert case.court == "Georgia Court of Appeals"
        assert case.court_id == "gactapp"
        assert case.opinion_id == 9001
        assert case.notes == "Dropping a party requires a motion and order."
        assert str(case.date_filed) == "2006-03-17"
        assert "Saved to case law: **Valdosta Hotel Properties" in text
        assert "```save-caselaw" not in text

    def test_existing_case_gets_proposition_appended(self, matter, user):
        CaseLaw.objects.create(
            matter=matter,
            case_name="Valdosta Hotel Properties, LLC v. White",
            citation="278 Ga. App. 206",
            cluster_id=888,
            notes="Original note.",
        )
        apply_caselaw_blocks(
            block([{"cluster_id": 888, "proposition": "Second proposition."}]),
            matter,
            user,
        )
        case = CaseLaw.objects.get(matter=matter, cluster_id=888)
        assert CaseLaw.objects.filter(matter=matter, cluster_id=888).count() == 1
        assert case.notes == "Original note.\nSecond proposition."

    def test_unknown_cluster_saves_nothing(self, matter, user):
        text = apply_caselaw_blocks(
            block([{"cluster_id": 999, "proposition": "x"}]), matter, user
        )
        assert not CaseLaw.objects.filter(matter=matter).exists()
        assert "(no cases saved)" in text

    def test_malformed_block_left_in_place(self, matter, user):
        raw = "```save-caselaw\nnot json\n```"
        assert apply_caselaw_blocks(raw, matter, user) == raw


class TestTrigger:
    def test_trigger_matches_research_talk(self):
        assert CASELAW_TRIGGER_RE.search("research the joinder issue and save it")
        assert CASELAW_TRIGGER_RE.search("what authority supports this?")
        assert not CASELAW_TRIGGER_RE.search("draft an email to the client")
