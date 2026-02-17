from decimal import Decimal

import pytest
from django.test import RequestFactory
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.activity.time.models import TimeEntry
from apps.invoicing.collection.get_collection_data import get_collection_data
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment

pytestmark = pytest.mark.django_db


# -----------------------------------------------------------
# get_collection_data business logic
# -----------------------------------------------------------
class TestGetCollectionData:
    def _make_request(self, user):
        factory = RequestFactory()
        request = factory.get("/invoicing/collection/")
        request.user = user
        request.session = {}
        return request

    def test_empty_when_no_invoices(self, user, matter):
        request = self._make_request(user)
        result = get_collection_data(request)
        assert list(result["matters"]) == []
        assert result["total_due_after_deferrals"] == 0

    def test_matter_with_balance_due(self, user, matter, sent_invoice):
        """Matter with $1000 SENT invoice and no payments has $1000 balance."""
        request = self._make_request(user)
        result = get_collection_data(request)
        matters = list(result["matters"])
        assert len(matters) == 1
        assert matters[0].billed == Decimal("1000.00")
        assert matters[0].balance_due == Decimal("1000.00")

    def test_payment_reduces_balance(self, user, matter, sent_invoice, payment_partial):
        """Payment of $400 reduces balance from $1000 to $600."""
        request = self._make_request(user)
        result = get_collection_data(request)
        matters = list(result["matters"])
        assert len(matters) == 1
        assert matters[0].balance_due == Decimal("600.00")

    def test_credit_reduces_balance(self, user, matter, sent_invoice, credit_small):
        """Credit of $100 reduces balance from $1000 to $900."""
        request = self._make_request(user)
        result = get_collection_data(request)
        matters = list(result["matters"])
        assert len(matters) == 1
        assert matters[0].balance_due == Decimal("900.00")

    def test_payment_and_credit_reduce_balance(
        self, user, matter, sent_invoice, payment_partial, credit_small
    ):
        """$400 payment + $100 credit = $500 balance on $1000 invoice."""
        request = self._make_request(user)
        result = get_collection_data(request)
        matters = list(result["matters"])
        assert len(matters) == 1
        assert matters[0].balance_due == Decimal("500.00")

    def test_fully_paid_matter_excluded(self, user, matter, sent_invoice):
        """Matter with zero balance is excluded from collection."""
        Payment.objects.create(
            matter=matter,
            date="2024-12-15",
            amount=Decimal("1000.00"),
            payment_method="CHECK",
        )
        request = self._make_request(user)
        result = get_collection_data(request)
        assert list(result["matters"]) == []

    def test_draft_invoices_excluded_from_billed(self, user, matter):
        """DRAFT invoices don't count as billed."""
        Invoice.objects.create(
            created_by=user,
            matter=matter,
            date_limit="2024-11-30",
            date_issued="2024-11-01",
            status="DRAFT",
        )
        request = self._make_request(user)
        result = get_collection_data(request)
        assert list(result["matters"]) == []

    def test_deferred_affects_due_after_deferrals(self, user, matter):
        """Deferred invoices reduce due_after_deferrals but not balance_due."""
        invoice = Invoice.objects.create(
            created_by=user,
            matter=matter,
            date_limit="2024-12-31",
            date_issued="2024-12-01",
            status="DEFERRED",
        )
        TimeEntry.objects.create(
            user=user,
            matter=matter,
            date="2024-01-01",
            actions="Deferred work",
            hours=Decimal("2.0"),
            rate=500,
            comp=False,
            entered=False,
            invoice=invoice,
        )
        request = self._make_request(user)
        result = get_collection_data(request)
        matters = list(result["matters"])
        assert len(matters) == 1
        # Billed and balance_due include deferred
        assert matters[0].billed == Decimal("1000.00")
        assert matters[0].balance_due == Decimal("1000.00")
        # But due_after_deferrals subtracts deferred amount
        assert matters[0].due_after_deferrals == Decimal("0.00")

    def test_total_due_after_deferrals(
        self, user, matter, sent_invoice, payment_partial
    ):
        request = self._make_request(user)
        result = get_collection_data(request)
        # $1000 - $400 = $600, no deferrals
        assert result["total_due_after_deferrals"] == Decimal("600.00")


# -----------------------------------------------------------
# Collection views
# -----------------------------------------------------------
class TestCollectionViews:
    def test_collection_index(self, client):
        url = reverse("invoicing:collection-index")
        response = client.get(url)
        assert response.status_code == 200
        assertTemplateUsed(response, "invoicing/collection/main.html")
        assert response.context["app"] == "invoicing"
        assert response.context["subapp"] == "collection"

    def test_collection_list(self, client):
        url = reverse("invoicing:collection-list")
        response = client.get(url)
        assert response.status_code == 200
        assertTemplateUsed(response, "invoicing/collection/list.html")
