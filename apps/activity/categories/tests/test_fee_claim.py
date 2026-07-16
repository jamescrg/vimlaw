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
    def test_sections_net_math_and_order(
        self, user, matter, category, category_2, unclaimed_category
    ):
        from apps.activity.expenses.models import ExpenseEntry

        # category (position 0): one billed + one comp entry (listed, not
        # counted), plus a categorized expense.
        make_entry(user, matter, hours=2.0, rate=300, category=category)
        make_entry(user, matter, hours=1.0, rate=300, comp=True, category=category)
        ExpenseEntry.objects.create(
            user=user,
            matter=matter,
            date="2020-01-07",
            description="Filing fee",
            amount=50,
            activity_category=category,
        )
        # category_2 (position 1): one entry.
        make_entry(user, matter, hours=0.5, rate=200, category=category_2)
        # Unclaimed category entries stay out by default.
        make_entry(user, matter, hours=9.0, rate=999, category=unclaimed_category)

        context = build_fee_claim_context(matter)
        sections = context["sections"]

        assert [s["title"] for s in sections] == [category.name, category_2.name]
        # Comp entry is listed but excluded from the net.
        assert len(sections[0]["entries"]) == 2
        assert sections[0]["fees_net"] == 600
        assert sections[0]["expenses_net"] == 50
        assert sections[1]["fees_net"] == 100
        assert context["has_unclaimed"] is False
        assert context["grand_totals"] == {"fees": 700, "expenses": 50}

    def test_uncategorized_follows_matter_switch(self, user, matter, category):
        make_entry(user, matter, hours=1.0, rate=100, category=category)
        make_entry(user, matter, hours=1.0, rate=50)  # uncategorized

        # Default: uncategorized is claimed → gets a section.
        context = build_fee_claim_context(matter)
        assert [s["title"] for s in context["sections"]] == [
            category.name,
            "Uncategorized",
        ]
        assert context["sections"][1]["claimed"] is True

        # Switched off: uncategorized is unclaimed → only with include_unclaimed.
        matter.uncategorized_claimed = False
        matter.save()
        context = build_fee_claim_context(matter)
        assert [s["title"] for s in context["sections"]] == [category.name]

        context = build_fee_claim_context(matter, include_unclaimed=True)
        assert [s["title"] for s in context["sections"]] == [
            category.name,
            "Uncategorized",
        ]
        assert context["sections"][1]["claimed"] is False
        assert context["has_unclaimed"] is True
        assert context["claimed_totals"] == {"fees": 100, "expenses": 0}
        assert context["unclaimed_totals"] == {"fees": 50, "expenses": 0}
        assert context["grand_totals"] == {"fees": 150, "expenses": 0}

    def test_include_unclaimed_categories(
        self, user, matter, category, unclaimed_category
    ):
        make_entry(user, matter, hours=1.0, rate=100, category=category)
        make_entry(user, matter, hours=1.0, rate=200, category=unclaimed_category)

        context = build_fee_claim_context(matter, include_unclaimed=True)
        titles = [s["title"] for s in context["sections"]]
        assert unclaimed_category.name in titles
        assert context["claimed_totals"]["fees"] == 100
        assert context["unclaimed_totals"]["fees"] == 200

    def test_foreign_matter_entries_excluded(
        self, user, matter, other_matter, category
    ):
        # A category left on an entry that moved matters can't leak in.
        make_entry(user, other_matter, hours=5.0, rate=100, category=category)

        context = build_fee_claim_context(matter)
        assert context["sections"] == []

    def test_empty_categories_skipped(self, matter, category):
        context = build_fee_claim_context(matter)
        assert context["sections"] == []
        assert context["grand_totals"] == {"fees": 0, "expenses": 0}

    def test_pdf_view_with_options(self, client, user, matter, category):
        make_entry(user, matter, category=category)
        response = client.get(
            reverse("matters:fee-claim-report", kwargs={"id": matter.id}),
            {"include_unclaimed": "on"},
        )
        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert response.content[:4] == b"%PDF"

    def test_options_modal_defaults_from_matter(self, client, matter):
        response = client.get(
            reverse("matters:fee-claim-report-modal", kwargs={"id": matter.id})
        )
        assert response.status_code == 200
        # Defaults to including unclaimed (the matter field's default). The
        # checkbox is the modal's only "checked" attribute.
        assert b"include_unclaimed" in response.content
        assert b"checked" in response.content

        matter.report_include_unclaimed = False
        matter.save()
        response = client.get(
            reverse("matters:fee-claim-report-modal", kwargs={"id": matter.id})
        )
        assert b"include_unclaimed" in response.content
        assert b"checked" not in response.content

    def test_generating_persists_option_to_matter(self, client, user, matter, category):
        make_entry(user, matter, category=category)

        # Unchecked checkbox → key absent → option off, saved to the matter.
        client.get(reverse("matters:fee-claim-report", kwargs={"id": matter.id}))
        matter.refresh_from_db()
        assert matter.report_include_unclaimed is False

        client.get(
            reverse("matters:fee-claim-report", kwargs={"id": matter.id}),
            {"include_unclaimed": "on"},
        )
        matter.refresh_from_db()
        assert matter.report_include_unclaimed is True


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
