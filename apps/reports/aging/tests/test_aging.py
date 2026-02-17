from decimal import Decimal

import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.invoicing.invoices.models import Invoice
from apps.reports.aging.views import _get_aging_data, _get_bucket

pytestmark = pytest.mark.django_db


# -----------------------------------------------------------
# _get_bucket unit tests
# -----------------------------------------------------------
class TestGetBucket:
    def test_current_0_days(self):
        assert _get_bucket(0) == "current"

    def test_current_30_days(self):
        assert _get_bucket(30) == "current"

    def test_31_60_days(self):
        assert _get_bucket(31) == "days_31_60"
        assert _get_bucket(60) == "days_31_60"

    def test_61_90_days(self):
        assert _get_bucket(61) == "days_61_90"
        assert _get_bucket(90) == "days_61_90"

    def test_91_120_days(self):
        assert _get_bucket(91) == "days_91_120"
        assert _get_bucket(120) == "days_91_120"

    def test_over_120_days(self):
        assert _get_bucket(121) == "days_over_120"
        assert _get_bucket(365) == "days_over_120"


# -----------------------------------------------------------
# _get_aging_data
# -----------------------------------------------------------
class TestGetAgingData:
    def test_empty_when_no_sent_invoices(self):
        client_data, grand_totals = _get_aging_data()
        assert client_data == []
        assert grand_totals["total"] == 0

    def test_single_current_invoice(self, user, matter_alpha):
        from apps.reports.aging.tests.conftest import _create_sent_invoice

        _create_sent_invoice(
            user, matter_alpha, days_old=10, amount_hours=Decimal("2"), rate=500
        )
        client_data, grand_totals = _get_aging_data()
        assert len(client_data) == 1
        assert client_data[0]["current"] == Decimal("1000.00")
        assert grand_totals["current"] == Decimal("1000.00")
        assert grand_totals["total"] == Decimal("1000.00")

    def test_invoice_in_31_60_bucket(self, user, matter_alpha):
        from apps.reports.aging.tests.conftest import _create_sent_invoice

        _create_sent_invoice(
            user, matter_alpha, days_old=45, amount_hours=Decimal("1"), rate=200
        )
        client_data, grand_totals = _get_aging_data()
        assert client_data[0]["days_31_60"] == Decimal("200.00")

    def test_invoice_in_over_120_bucket(self, user, matter_alpha):
        from apps.reports.aging.tests.conftest import _create_sent_invoice

        _create_sent_invoice(
            user, matter_alpha, days_old=150, amount_hours=Decimal("1"), rate=300
        )
        client_data, grand_totals = _get_aging_data()
        assert client_data[0]["days_over_120"] == Decimal("300.00")

    def test_multiple_buckets_same_client(self, user, matter_alpha):
        from apps.reports.aging.tests.conftest import _create_sent_invoice

        _create_sent_invoice(
            user, matter_alpha, days_old=10, amount_hours=Decimal("1"), rate=100
        )
        _create_sent_invoice(
            user, matter_alpha, days_old=50, amount_hours=Decimal("1"), rate=200
        )
        client_data, grand_totals = _get_aging_data()
        assert len(client_data) == 1
        assert client_data[0]["current"] == Decimal("100.00")
        assert client_data[0]["days_31_60"] == Decimal("200.00")
        assert client_data[0]["total"] == Decimal("300.00")

    def test_multiple_clients(self, user, matter_alpha, matter_beta):
        from apps.reports.aging.tests.conftest import _create_sent_invoice

        _create_sent_invoice(
            user, matter_alpha, days_old=10, amount_hours=Decimal("1"), rate=100
        )
        _create_sent_invoice(
            user, matter_beta, days_old=10, amount_hours=Decimal("1"), rate=200
        )
        client_data, grand_totals = _get_aging_data()
        assert len(client_data) == 2
        assert grand_totals["total"] == Decimal("300.00")

    def test_sorted_by_client_name_asc(self, user, matter_alpha, matter_beta):
        from apps.reports.aging.tests.conftest import _create_sent_invoice

        _create_sent_invoice(
            user, matter_beta, days_old=10, amount_hours=Decimal("1"), rate=100
        )
        _create_sent_invoice(
            user, matter_alpha, days_old=10, amount_hours=Decimal("1"), rate=100
        )
        client_data, _ = _get_aging_data(sort_by="client_name", sort_direction="asc")
        assert client_data[0]["client_name"] == "Alpha Client"
        assert client_data[1]["client_name"] == "Beta Client"

    def test_sorted_by_total_desc(self, user, matter_alpha, matter_beta):
        from apps.reports.aging.tests.conftest import _create_sent_invoice

        _create_sent_invoice(
            user, matter_alpha, days_old=10, amount_hours=Decimal("1"), rate=100
        )
        _create_sent_invoice(
            user, matter_beta, days_old=10, amount_hours=Decimal("1"), rate=500
        )
        client_data, _ = _get_aging_data(sort_by="total", sort_direction="desc")
        assert client_data[0]["client_name"] == "Beta Client"
        assert client_data[1]["client_name"] == "Alpha Client"

    def test_excludes_zero_remaining_invoices(self, user, matter_alpha):
        """SENT invoices with 0 amount remaining (legacy PAID) are excluded."""
        from apps.reports.aging.tests.conftest import _create_sent_invoice

        _create_sent_invoice(
            user, matter_alpha, days_old=10, amount_hours=Decimal("0"), rate=0
        )
        client_data, grand_totals = _get_aging_data()
        assert client_data == []

    def test_paid_status_excluded(self, user, matter_alpha):
        """Only SENT invoices appear in aging, not PAID."""
        Invoice.objects.create(
            created_by=user,
            matter=matter_alpha,
            date_limit="2024-12-31",
            date_issued="2024-12-01",
            status="PAID",
        )
        client_data, _ = _get_aging_data()
        assert client_data == []

    def test_grand_totals_across_clients(self, user, matter_alpha, matter_beta):
        from apps.reports.aging.tests.conftest import _create_sent_invoice

        _create_sent_invoice(
            user, matter_alpha, days_old=10, amount_hours=Decimal("1"), rate=100
        )
        _create_sent_invoice(
            user, matter_beta, days_old=50, amount_hours=Decimal("1"), rate=200
        )
        _, grand_totals = _get_aging_data()
        assert grand_totals["current"] == Decimal("100.00")
        assert grand_totals["days_31_60"] == Decimal("200.00")
        assert grand_totals["total"] == Decimal("300.00")


# -----------------------------------------------------------
# Aging views
# -----------------------------------------------------------
class TestAgingViews:
    def test_aging_index(self, client):
        url = reverse("reports:aging-index")
        response = client.get(url)
        assert response.status_code == 200
        assertTemplateUsed(response, "reports/aging/main.html")
        assert "client_data" in response.context
        assert "grand_totals" in response.context

    def test_aging_list(self, client):
        url = reverse("reports:aging")
        response = client.get(url)
        assert response.status_code == 200
        assertTemplateUsed(response, "reports/aging/list.html")

    def test_aging_sort_params(self, client):
        url = reverse("reports:aging-index")
        response = client.get(url, {"sort": "total", "direction": "desc"})
        assert response.status_code == 200
        assert response.context["current_sort"] == "total"
        assert response.context["current_direction"] == "desc"
