from decimal import Decimal

import pytest
from django.test import RequestFactory
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.unbilled.unbilled import get_unbilled_data

pytestmark = pytest.mark.django_db


# -----------------------------------------------------------
# get_unbilled_data business logic
# -----------------------------------------------------------
class TestGetUnbilledData:
    def _make_request(self, user):
        factory = RequestFactory()
        request = factory.get("/invoicing/unbilled/")
        request.user = user
        request.session = {}
        return request

    def test_empty_when_no_entries(self, user):
        request = self._make_request(user)
        result = get_unbilled_data(request)
        assert list(result["matters"]) == []
        assert result["total_hours"] == 0
        assert result["total_fees"] == 0
        assert result["total_expenses"] == 0

    def test_unbilled_time_included(self, user, matter, unbilled_time):
        request = self._make_request(user)
        result = get_unbilled_data(request)
        matters = list(result["matters"])
        assert len(matters) == 1
        assert matters[0].unbilled_hours == Decimal("2.0")
        assert matters[0].unbilled_fees == Decimal("600.00")

    def test_unbilled_expense_included(self, user, matter, unbilled_expense):
        request = self._make_request(user)
        result = get_unbilled_data(request)
        matters = list(result["matters"])
        assert len(matters) == 1
        assert matters[0].unbilled_expenses == Decimal("150.00")

    def test_totals(self, user, matter, unbilled_time, unbilled_expense):
        request = self._make_request(user)
        result = get_unbilled_data(request)
        assert result["total_hours"] == Decimal("2.0")
        assert result["total_fees"] == Decimal("600.00")
        assert result["total_expenses"] == Decimal("150.00")
        assert result["total_activity"] == Decimal("750.00")

    def test_comped_entries_excluded(self, user, matter):
        """Comped time and expenses should not appear in unbilled."""
        TimeEntry.objects.create(
            user=user,
            matter=matter,
            date="2024-12-01",
            actions="Comped work",
            hours=Decimal("1.0"),
            rate=300,
            comp=True,
            entered=False,
            invoice=None,
        )
        ExpenseEntry.objects.create(
            user=user,
            matter=matter,
            date="2024-12-01",
            description="Comped expense",
            amount=Decimal("50.00"),
            comp=True,
            entered=False,
            invoice=None,
        )
        request = self._make_request(user)
        result = get_unbilled_data(request)
        assert list(result["matters"]) == []

    def test_invoiced_entries_excluded(self, user, matter):
        """Entries linked to an invoice should not appear in unbilled."""
        invoice = Invoice.objects.create(
            created_by=user,
            matter=matter,
            date_limit="2024-12-31",
            date_issued="2024-12-01",
            status="SENT",
        )
        TimeEntry.objects.create(
            user=user,
            matter=matter,
            date="2024-12-01",
            actions="Invoiced work",
            hours=Decimal("1.0"),
            rate=300,
            comp=False,
            entered=False,
            invoice=invoice,
        )
        request = self._make_request(user)
        result = get_unbilled_data(request)
        assert list(result["matters"]) == []

    def test_entered_entries_excluded(self, user, matter):
        """Entries marked as entered should not appear in unbilled."""
        TimeEntry.objects.create(
            user=user,
            matter=matter,
            date="2024-12-01",
            actions="Entered work",
            hours=Decimal("1.0"),
            rate=300,
            comp=False,
            entered=True,
            invoice=None,
        )
        request = self._make_request(user)
        result = get_unbilled_data(request)
        assert list(result["matters"]) == []

    def test_total_activity_is_fees_plus_expenses(
        self, user, matter, unbilled_time, unbilled_expense
    ):
        request = self._make_request(user)
        result = get_unbilled_data(request)
        matters = list(result["matters"])
        # $600 fees + $150 expenses = $750
        assert matters[0].total_activity == Decimal("750.00")

    def test_clearance_with_no_trust_balance(self, user, matter, unbilled_time):
        """Clearance is 0 when client has no trust balance."""
        request = self._make_request(user)
        result = get_unbilled_data(request)
        matters = list(result["matters"])
        assert matters[0].clearance == 0

    def test_matter_with_only_expenses(self, user, matter, unbilled_expense):
        """Matters with only unbilled expenses (no time) are included."""
        request = self._make_request(user)
        result = get_unbilled_data(request)
        matters = list(result["matters"])
        assert len(matters) == 1
        assert matters[0].unbilled_hours == 0
        assert matters[0].unbilled_expenses == Decimal("150.00")


# -----------------------------------------------------------
# Unbilled views
# -----------------------------------------------------------
class TestUnbilledViews:
    def test_unbilled_index(self, client):
        url = reverse("invoicing:unbilled-index")
        response = client.get(url)
        assert response.status_code == 200
        assertTemplateUsed(response, "invoicing/unbilled/main.html")
        assert response.context["app"] == "invoicing"
        assert response.context["subapp"] == "unbilled"

    def test_unbilled_list(self, client):
        url = reverse("invoicing:unbilled-list")
        response = client.get(url)
        assert response.status_code == 200
        assertTemplateUsed(response, "invoicing/unbilled/list.html")

    def test_unbilled_sort(self, client):
        url = reverse("invoicing:unbilled-sort", args=["unbilled_fees"])
        response = client.get(url)
        # unbilled_sort redirects
        assert response.status_code == 302
