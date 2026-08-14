"""Tests for the matter-scope JSON API behind the Claude Desktop MCP
server: auth, section reads, full-content reads, and the create-only
fact/witness/task writes."""

import json
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.activity.expenses.models import ExpenseEntry
from apps.activity.flat_fees.models import FlatFeeEntry
from apps.activity.models import ActivityCategory
from apps.activity.time.models import TimeEntry
from apps.calendar.models import Event
from apps.case.models import Fact, Witness
from apps.drafts.models import CompanionToken
from apps.mail.models import Email
from apps.matters.models import Matter
from apps.matters.rates.models import Rate
from apps.matters.settlement.models import SettlementEntry
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def api(user):
    return Client(HTTP_X_KOSMOS_TOKEN=CompanionToken.for_user(user).key)


@pytest.fixture
def restricted_api():
    """Token client for a non-admin user with no matter memberships."""
    outsider = CustomUser.objects.create(
        username="case-outsider",
        email="case-outsider@example.com",
        user_rate=100,
        perm_all_matters=False,
    )
    return Client(HTTP_X_KOSMOS_TOKEN=CompanionToken.for_user(outsider).key)


def section_url(matter, section):
    return f"/case/api/matter/{matter.id}/{section}/"


def post_json(api, url, payload):
    return api.post(url, json.dumps(payload), content_type="application/json")


def section_text(api, matter, section):
    response = api.get(section_url(matter, section))
    assert response.status_code == 200
    return response.json()["text"]


class TestAccess:
    def test_missing_token_is_401(self, matter):
        response = Client().get(section_url(matter, "overview"))
        assert response.status_code == 401

    def test_denied_matter_is_404(self, restricted_api, matter):
        response = restricted_api.get(section_url(matter, "overview"))
        assert response.status_code == 404

    def test_closed_matter_is_404(self, api, matter):
        matter.status = "Closed"
        matter.save()
        response = api.get(section_url(matter, "overview"))
        assert response.status_code == 404

    def test_unknown_section_is_400_listing_sections(self, api, matter):
        response = api.get(section_url(matter, "bogus"))
        assert response.status_code == 400
        assert "overview" in response.json()["error"]


class TestSections:
    def test_overview(self, api, matter):
        text = section_text(api, matter, "overview")
        assert "Test Matter" in text
        assert "Test Client" in text

    def test_rates_with_matter_and_firm_rows(self, api, matter, user):
        Rate.objects.create(user=user, matter=matter, matter_rate=250)
        Rate.objects.create(user=user, matter=None, matter_rate=100)
        text = section_text(api, matter, "rates")
        assert "$250/hr" in text
        assert "Firm default rates:" in text
        assert "$100/hr" in text

    def test_activity_with_categories_and_totals(self, api, matter, user):
        category = ActivityCategory.objects.create(matter=matter, name="Drafting")
        TimeEntry.objects.create(
            matter=matter,
            user=user,
            date="2026-01-05",
            actions="Draft complaint",
            hours=2,
            rate=200,
            category=category,
        )
        ExpenseEntry.objects.create(
            matter=matter,
            user=user,
            date="2026-01-06",
            category="Filing fee",
            description="Clerk of court",
            amount=100,
        )
        FlatFeeEntry.objects.create(
            matter=matter,
            user=user,
            date="2026-01-07",
            description="Initial consult",
            amount=500,
        )
        text = section_text(api, matter, "activity")
        assert "[Drafting] Draft complaint" in text
        assert "$400.00" in text  # 2h @ $200
        assert "Filing fee: Clerk of court ($100.00)" in text
        assert "Initial consult ($500.00)" in text

    def test_events(self, api, matter, user):
        Event.objects.create(
            user=user,
            matter=matter,
            date=(timezone.now() + timedelta(days=7)).date(),
            description="Status hearing",
        )
        assert "Status hearing" in section_text(api, matter, "events")

    def test_tasks(self, api, matter, user):
        Task.objects.create(
            user=user, matter=matter, description="call the expert", status="Pending"
        )
        assert "Call the expert" in section_text(api, matter, "tasks")

    def test_settlement(self, api, matter, user):
        SettlementEntry.objects.create(
            user=user, matter=matter, date="2026-02-01", type="Demand", amount=50000
        )
        text = section_text(api, matter, "settlement")
        assert "Demand: $50,000.00" in text

    def test_documents_manifest_without_ocr_text(self, api, matter, document):
        document.ocr_text = "SECRET EXTRACTED TEXT"
        document.save(update_fields=["ocr_text"])
        text = section_text(api, matter, "documents")
        assert f"[doc:{document.id}] Test Document" in text
        assert "SECRET EXTRACTED TEXT" not in text

    def test_highlights_manifest(self, api, matter, highlight):
        text = section_text(api, matter, "highlights")
        assert f"[hl:{highlight.id}]" in text
        assert "highlighted text" in text

    def test_timeline(self, api, matter, fact):
        text = section_text(api, matter, "timeline")
        assert "Important event occurred" in text

    def test_witnesses(self, api, matter, user):
        Witness.objects.create(
            matter=matter, user=user, name="Jordan Reeves", alignment="friendly"
        )
        assert "Jordan Reeves" in section_text(api, matter, "witnesses")

    def test_emails_thread_manifest(self, api, matter):
        for i, gmail_id in enumerate(["m1", "m2"]):
            Email.objects.create(
                matter=matter,
                gmail_id=gmail_id,
                thread_id="t100",
                sender="Opposing Counsel <oc@example.com>",
                recipients="james@example.com",
                subject="Discovery schedule",
                snippet="Proposed dates attached",
                body_text=f"Message body {i}",
                date=timezone.now() - timedelta(days=2 - i),
            )
        text = section_text(api, matter, "emails")
        assert "[thread t100] Discovery schedule (2 messages" in text


class TestFullReads:
    def test_document_text(self, api, document):
        document.ocr_text = "Full extracted document text."
        document.save(update_fields=["ocr_text"])
        response = api.get(f"/case/api/documents/{document.id}/")
        assert response.status_code == 200
        assert response.json()["text"] == "Full extracted document text."

    def test_document_denied_is_404(self, restricted_api, document):
        response = restricted_api.get(f"/case/api/documents/{document.id}/")
        assert response.status_code == 404

    def test_email_thread(self, api, matter):
        Email.objects.create(
            matter=matter,
            gmail_id="m1",
            thread_id="t200",
            sender="oc@example.com",
            recipients="james@example.com",
            subject="Depo dates",
            body_text="How about Tuesday?",
            date=timezone.now(),
        )
        response = api.get(f"/case/api/matter/{matter.id}/emails/t200/")
        assert response.status_code == 200
        body = response.json()
        assert body["subject"] == "Depo dates"
        assert "How about Tuesday?" in body["text"]

    def test_unknown_thread_is_404(self, api, matter):
        response = api.get(f"/case/api/matter/{matter.id}/emails/nope/")
        assert response.status_code == 404


class TestFactCreate:
    def test_create_links_in_matter_sources_only(self, api, matter, highlight):
        response = post_json(
            api,
            section_url(matter, "facts"),
            {
                "description": "Contract signed by both parties",
                "date": "2024-03-01",
                "highlights": [highlight.id],
                "documents": [999999],
            },
        )
        assert response.status_code == 201
        fact = Fact.objects.get(pk=response.json()["id"])
        assert fact.matter_id == matter.id
        assert list(fact.highlights.values_list("id", flat=True)) == [highlight.id]
        assert fact.documents.count() == 0
        assert response.json()["message"].startswith("- Added to timeline:")

    def test_short_description_is_400(self, api, matter):
        response = post_json(api, section_url(matter, "facts"), {"description": "ab"})
        assert response.status_code == 400

    def test_denied_matter_is_404(self, restricted_api, matter):
        response = post_json(
            restricted_api, section_url(matter, "facts"), {"description": "whatever"}
        )
        assert response.status_code == 404

    def test_get_serves_timeline_section(self, api, matter, fact):
        response = api.get(section_url(matter, "facts"))
        assert response.status_code == 200
        assert "Important event occurred" in response.json()["text"]


class TestWitnessCreate:
    def test_create_and_dedup(self, api, matter):
        url = section_url(matter, "witnesses")
        response = post_json(
            api, url, {"name": "Dana Whitfield", "alignment": "hostile"}
        )
        assert response.status_code == 201
        assert response.json()["created"] is True

        response = post_json(api, url, {"name": "dana whitfield"})
        assert response.status_code == 200
        assert response.json()["created"] is False
        assert Witness.objects.filter(matter=matter).count() == 1

    def test_missing_name_is_400(self, api, matter):
        response = post_json(api, section_url(matter, "witnesses"), {"name": "x"})
        assert response.status_code == 400


class TestTaskCreate:
    def test_admin_task_without_matter(self, api, user):
        response = post_json(api, "/case/api/tasks/", {"description": "file cabinet"})
        assert response.status_code == 201
        assert response.json()["matter"] == "Admin"
        task = Task.objects.get(pk=response.json()["id"])
        assert task.matter is None
        assert task.user_id == user.id

    def test_matter_task(self, api, matter):
        response = post_json(
            api,
            "/case/api/tasks/",
            {
                "description": "serve the subpoena",
                "matter_id": matter.id,
                "due": "2026-09-01",
            },
        )
        assert response.status_code == 201
        task = Task.objects.get(pk=response.json()["id"])
        assert task.matter_id == matter.id
        assert str(task.date_due) == "2026-09-01"

    def test_denied_matter_is_404(self, restricted_api, matter):
        response = post_json(
            restricted_api,
            "/case/api/tasks/",
            {"description": "should not exist", "matter_id": matter.id},
        )
        assert response.status_code == 404
        assert not Task.objects.filter(description__icontains="should not").exists()

    def test_duplicate_matter_name_resolves_to_requested_id(self, api, matter, user):
        twin = Matter.objects.create(
            user=user, name=matter.name, status="Open", date_start="2024-02-01"
        )
        response = post_json(
            api,
            "/case/api/tasks/",
            {"description": "task for the twin", "matter_id": twin.id},
        )
        assert response.status_code == 201
        task = Task.objects.get(pk=response.json()["id"])
        assert task.matter_id == twin.id
