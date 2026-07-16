"""Tests for the fee claim report and the matter-tab category filter."""

import pytest
from django.urls import reverse

from apps.activity.time.models import TimeEntry
from apps.matters.generate_fee_claim_report import build_fee_claim_context

pytestmark = pytest.mark.django_db


def make_entry(user, matter, **kwargs):
    defaults = {
        "date": "2020-01-07",
        "actions": "Draft motion",
        "hours": 1.0,
        "rate": 300,
        "comp": False,
        "entered": False,
    }
    defaults.update(kwargs)
    return TimeEntry.objects.create(user=user, matter=matter, **defaults)


class TestFeeClaimReport:
    def test_sections_math_and_order(
        self, user, matter, category, category_2, unclaimed_category
    ):
        # category (position 0): one billed + one comp entry.
        make_entry(user, matter, hours=2.0, rate=300, category=category)
        make_entry(user, matter, hours=1.0, rate=300, comp=True, category=category)
        # category_2 (position 1): one entry.
        make_entry(user, matter, hours=0.5, rate=200, category=category_2)
        # Unclaimed and uncategorized entries stay out entirely.
        make_entry(user, matter, hours=9.0, rate=999, category=unclaimed_category)
        make_entry(user, matter, hours=8.0, rate=999)

        context = build_fee_claim_context(matter)
        sections = context["sections"]

        assert [s["category"] for s in sections] == [category, category_2]
        assert sections[0]["gross"] == 900
        assert sections[0]["comp"] == 300
        assert sections[0]["net"] == 600
        assert sections[1]["net"] == 100
        assert context["claim_total"] == 700

    def test_foreign_matter_entries_excluded(
        self, user, matter, other_matter, category
    ):
        # A category left on an entry that moved matters can't leak in.
        make_entry(user, other_matter, hours=5.0, rate=100, category=category)

        context = build_fee_claim_context(matter)
        assert context["sections"] == []

    def test_empty_claimed_categories_skipped(self, matter, category):
        context = build_fee_claim_context(matter)
        assert context["sections"] == []
        assert context["claim_total"] == 0

    def test_pdf_view(self, client, user, matter, category):
        make_entry(user, matter, category=category)
        response = client.get(
            reverse("matters:fee-claim-report", kwargs={"id": matter.id})
        )
        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert response.content[:4] == b"%PDF"


class TestMatterCategoryFilter:
    def filter_url(self, matter):
        return reverse("matters:activity-filter-category", kwargs={"id": matter.id})

    def list_url(self, matter):
        return reverse("matters:activity", kwargs={"id": matter.id})

    def test_filter_by_category(self, client, user, matter, category, category_2):
        shown = make_entry(user, matter, actions="Shown entry", category=category)
        make_entry(user, matter, actions="Hidden entry", category=category_2)

        response = client.post(self.filter_url(matter), {"category": category.id})
        assert response.status_code == 204

        response = client.get(self.list_url(matter))
        assert shown.actions.encode() in response.content
        assert b"Hidden entry" not in response.content

    def test_uncategorized_option(self, client, user, matter, category):
        make_entry(user, matter, actions="Coded entry", category=category)
        uncoded = make_entry(user, matter, actions="Uncoded entry")

        client.post(self.filter_url(matter), {"category": "none"})
        response = client.get(self.list_url(matter))
        assert uncoded.actions.encode() in response.content
        assert b"Coded entry" not in response.content

    def test_all_clears_filter(self, client, user, matter, category):
        make_entry(user, matter, actions="Coded entry", category=category)
        make_entry(user, matter, actions="Uncoded entry")

        client.post(self.filter_url(matter), {"category": category.id})
        client.post(self.filter_url(matter), {"category": ""})
        response = client.get(self.list_url(matter))
        assert b"Coded entry" in response.content
        assert b"Uncoded entry" in response.content

    def test_foreign_category_id_ignored(
        self, client, user, matter, other_matter, category
    ):
        from apps.activity.models import ActivityCategory

        foreign = ActivityCategory.objects.create(name="Foreign", matter=other_matter)
        visible = make_entry(user, matter, actions="Still visible", category=category)

        client.post(self.filter_url(matter), {"category": foreign.id})
        response = client.get(self.list_url(matter))
        # A category from another matter can't stick — treated as All.
        assert visible.actions.encode() in response.content

    def test_select_all_respects_filter(
        self, client, user, matter, category, category_2
    ):
        in_filter = make_entry(user, matter, category=category)
        make_entry(user, matter, category=category_2)

        client.post(self.filter_url(matter), {"category": category.id})
        client.post(
            reverse("matters:activity-select-all", kwargs={"matter_id": matter.id})
        )
        selected = client.session[f"selected_matter_activity_{matter.id}"]
        assert selected == [in_filter.id]
