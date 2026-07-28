import json

import pytest

from apps.intakes.models import Intake

pytestmark = pytest.mark.django_db

ASSESSMENT = {
    "summary": "Boundary dispute over a neighbor's fence.",
    "analysis": "Solid boundary dispute that fits the practice.",
    "importance": 6,
    "follow_up_questions": ["Is there a survey?", "How long has the fence stood?"],
}


@pytest.fixture
def mock_ai(monkeypatch):
    def _set(payload):
        text = payload if isinstance(payload, str) else json.dumps(payload)
        monkeypatch.setattr(
            "apps.case.ai.gemini_client.send_to_gemini",
            lambda *args, **kwargs: (text, 10, 5),
        )

    return _set


def test_detail_shows_assessment_pane_empty_state(client, intake):
    response = client.get(f"/intakes/{intake.id}/")
    assert response.status_code == 200
    assert b"Assessment" in response.content  # the segmented-control pill
    assert b"No assessment yet" in response.content


def test_assess_stores_assessment_and_importance(client, intake, mock_ai):
    mock_ai(ASSESSMENT)
    response = client.post(f"/intakes/{intake.id}/assess")
    assert response.status_code == 200
    # Success refreshes the whole detail so the importance flag catches up
    assert response.headers.get("HX-Trigger") == "intakeDetailChanged"

    intake.refresh_from_db()
    assert intake.importance == 6
    assert intake.assessed_at is not None
    assert "## Summary\n\nBoundary dispute" in intake.assessment
    assert "## Analysis\n\nSolid boundary dispute" in intake.assessment
    # The blank line after the header keeps markdown from mashing the
    # numbered questions into one paragraph
    assert "## Follow-up questions\n\n1. Is there a survey?" in intake.assessment
    assert "\n2. How long has the fence stood?" in intake.assessment
    assert b"Kosmos" in response.content


def test_assess_null_importance_keeps_current(client, intake, mock_ai):
    Intake.objects.filter(id=intake.id).update(importance=6)
    mock_ai({**ASSESSMENT, "importance": None})
    client.post(f"/intakes/{intake.id}/assess")
    intake.refresh_from_db()
    assert intake.importance == 6


def test_assess_without_questions_has_no_section(client, intake, mock_ai):
    mock_ai({**ASSESSMENT, "follow_up_questions": []})
    client.post(f"/intakes/{intake.id}/assess")
    intake.refresh_from_db()
    assert "Follow-up questions" not in intake.assessment


def test_failed_assess_keeps_previous_assessment(client, intake, mock_ai):
    Intake.objects.filter(id=intake.id).update(assessment="Earlier read.")
    mock_ai("I refuse to answer in JSON.")
    response = client.post(f"/intakes/{intake.id}/assess")
    assert b"Assessment failed" in response.content
    assert "HX-Trigger" not in response.headers
    intake.refresh_from_db()
    assert intake.assessment == "Earlier read."


def test_detail_shows_stored_assessment(client, intake, mock_ai):
    mock_ai(ASSESSMENT)
    client.post(f"/intakes/{intake.id}/assess")
    response = client.get(f"/intakes/{intake.id}/")
    assert b"Solid boundary dispute" in response.content
    assert b"Update" in response.content
