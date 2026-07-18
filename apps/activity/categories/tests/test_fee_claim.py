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
        assert context["grand_totals"] == {
            "hours": 2.5,
            "fees": 700,
            "expenses": 50,
            "total": 750,
        }

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
        assert context["claimed_totals"] == {
            "hours": 1.0,
            "fees": 100,
            "expenses": 0,
            "total": 100,
        }
        assert context["unclaimed_totals"] == {
            "hours": 1.0,
            "fees": 50,
            "expenses": 0,
            "total": 50,
        }
        assert context["grand_totals"] == {
            "hours": 2.0,
            "fees": 150,
            "expenses": 0,
            "total": 150,
        }

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
        assert context["grand_totals"] == {
            "hours": 0,
            "fees": 0,
            "expenses": 0,
            "total": 0,
        }

    def test_pdf_view_with_options(self, client, user, matter, category):
        make_entry(user, matter, category=category)
        response = client.get(
            reverse("matters:fee-claim-report", kwargs={"id": matter.id}),
            {"include_unclaimed": "true"},
        )
        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert response.content[:4] == b"%PDF"

    def test_options_modal_defaults_from_matter(self, client, matter):
        import re

        def selected_option(content, name):
            block = re.search(
                rf'name="{name}".*?</select>', content.decode(), re.S
            ).group(0)
            return re.search(
                r'<option[^>]*value="(true|false)"[^>]*selected', block, re.S
            ).group(1)

        response = client.get(
            reverse("matters:fee-claim-report-modal", kwargs={"id": matter.id})
        )
        assert response.status_code == 200
        # Matter-field defaults: unclaimed/entries/grouped on, reclaim off.
        assert selected_option(response.content, "include_unclaimed") == "true"
        assert selected_option(response.content, "show_entries") == "true"
        assert selected_option(response.content, "group_by_category") == "true"
        assert selected_option(response.content, "reclaim_comp") == "false"

        matter.report_include_unclaimed = False
        matter.report_reclaim_comp = True
        matter.save()
        response = client.get(
            reverse("matters:fee-claim-report-modal", kwargs={"id": matter.id})
        )
        assert selected_option(response.content, "include_unclaimed") == "false"
        assert selected_option(response.content, "reclaim_comp") == "true"

    def test_generating_persists_options_to_matter(
        self, client, user, matter, category
    ):
        make_entry(user, matter, category=category)

        client.get(
            reverse("matters:fee-claim-report", kwargs={"id": matter.id}),
            {
                "include_unclaimed": "false",
                "show_entries": "true",
                "group_by_category": "false",
            },
        )
        matter.refresh_from_db()
        assert matter.report_include_unclaimed is False
        assert matter.report_show_entries is True
        assert matter.report_group_by_category is False

        client.get(
            reverse("matters:fee-claim-report", kwargs={"id": matter.id}),
            {
                "include_unclaimed": "true",
                "show_entries": "false",
                "group_by_category": "true",
                "reclaim_comp": "true",
            },
        )
        matter.refresh_from_db()
        assert matter.report_include_unclaimed is True
        assert matter.report_show_entries is False
        assert matter.report_group_by_category is True
        assert matter.report_reclaim_comp is True

    def test_reclaim_comp_uses_gross(self, user, matter, category):
        make_entry(user, matter, hours=2.0, rate=300, category=category)
        make_entry(user, matter, hours=1.0, rate=300, comp=True, category=category)

        context = build_fee_claim_context(matter)
        assert context["sections"][0]["fees_net"] == 600
        assert context["reclaim_comp"] is False

        context = build_fee_claim_context(matter, reclaim_comp=True)
        assert context["sections"][0]["fees_net"] == 900
        assert context["sections"][0]["hours"] == 3.0
        assert context["reclaim_comp"] is True
        assert context["grand_totals"]["fees"] == 900

    def test_timekeepers_have_rates(self, user, matter, category):
        from apps.matters.rates.models import Rate

        make_entry(user, matter, category=category)
        context = build_fee_claim_context(matter)
        # No matter rate set → user default.
        assert context["timekeepers"][0]["rate"] == user.user_rate

        Rate.objects.create(user=user, matter=matter, matter_rate=425)
        context = build_fee_claim_context(matter)
        assert context["timekeepers"][0]["rate"] == 425

    def test_ungrouped_mode_lists_chronologically(
        self, user, matter, category, category_2
    ):
        later = make_entry(user, matter, date="2020-02-01", category=category)
        earlier = make_entry(user, matter, date="2020-01-01", category=category_2)

        context = build_fee_claim_context(
            matter, show_entries=True, group_by_category=False
        )
        assert context["group_by_category"] is False
        # One run, date order — regardless of category grouping.
        assert context["all_entries"] == [earlier, later]

    def test_summary_only_mode(self, user, matter, category):
        make_entry(user, matter, category=category)
        context = build_fee_claim_context(matter, show_entries=False)
        assert context["show_entries"] is False
        # Summary data still present for the template.
        assert context["grand_totals"]["fees"] == 300


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


class TestReportTemplateModes:
    """Render the template per option mode and assert content markers —
    size-only smoke checks once let a mis-nested template through."""

    def render(self, matter, **kwargs):
        from django.template.loader import render_to_string

        return render_to_string(
            "matters/fee-claim-report.html", build_fee_claim_context(matter, **kwargs)
        )

    def test_summary_only_hides_entries_and_timekeepers(self, user, matter, category):
        make_entry(user, matter, actions="Detail row", category=category)
        html = self.render(matter, show_entries=False)
        assert "Summary" in html
        assert "Total Claim" in html
        assert "Timekeepers" not in html
        assert "Detail row" not in html

    def test_grouped_mode_sections(self, user, matter, category):
        make_entry(user, matter, actions="Detail row", category=category)
        html = self.render(matter, show_entries=True, group_by_category=True)
        assert "Timekeepers" in html
        assert "Detail row" in html
        assert "<h3>Time Entries</h3>" not in html

    def test_ungrouped_mode_single_listing(self, user, matter, category, category_2):
        make_entry(user, matter, actions="Detail row", category=category)
        make_entry(user, matter, actions="Other row", category=category_2)
        html = self.render(matter, show_entries=True, group_by_category=False)
        assert "<h3>Time Entries</h3>" in html
        assert "Detail row" in html and "Other row" in html
        # Summary + timekeepers + one combined listing table.
        assert html.count("</table>") == 3

    def test_claimed_column_only_with_unclaimed(self, user, matter, category):
        make_entry(user, matter, category=category)
        assert ">Claimed</th>" in self.render(matter, include_unclaimed=True)
        assert ">Claimed</th>" not in self.render(matter, include_unclaimed=False)

    def test_reclaim_comp_drops_strikethrough(self, user, matter, category):
        import re

        make_entry(user, matter, comp=True, category=category)

        html = self.render(matter)
        listing = html.split("Timekeepers", 1)[1]
        assert re.search(r'class="[^"]*\bcomp\b', listing)

        html = self.render(matter, reclaim_comp=True)
        listing = html.split("Timekeepers", 1)[1]
        assert not re.search(r'class="[^"]*\bcomp\b', listing)
