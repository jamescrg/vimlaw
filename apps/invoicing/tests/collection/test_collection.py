from decimal import Decimal

import pytest
from django.test import RequestFactory
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.activity.time.models import TimeEntry
from apps.invoicing.applications.models import PaymentApplication
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

    def _deferred_invoice(self, user, matter, hours, rate):
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
            hours=Decimal(hours),
            rate=rate,
            comp=False,
            entered=False,
            invoice=invoice,
        )
        return invoice

    def test_purely_deferred_matter_excluded(self, user, matter):
        """A matter whose only billing is deferred owes nothing now -> excluded."""
        self._deferred_invoice(user, matter, "2.0", 500)
        request = self._make_request(user)
        result = get_collection_data(request)
        assert list(result["matters"]) == []

    def test_payment_applied_to_deferred_not_double_counted(
        self, user, matter, sent_invoice
    ):
        """A payment applied to a deferred invoice must not reduce the balance
        owed on non-deferred invoices (regression: it previously went negative)."""
        deferred = self._deferred_invoice(user, matter, "1.0", 500)  # $500 deferred
        payment = Payment.objects.create(
            matter=matter,
            date="2024-12-15",
            amount=Decimal("500.00"),
            payment_method="WIRE",
        )
        PaymentApplication.objects.create(
            payment=payment, invoice=deferred, amount_applied=Decimal("500.00")
        )
        request = self._make_request(user)
        result = get_collection_data(request)
        matters = list(result["matters"])
        assert len(matters) == 1
        # billed = $1000 SENT + $500 deferred; the deferred payment is added back
        # so due_after_deferrals reflects only the unpaid SENT invoice.
        assert matters[0].due_after_deferrals == Decimal("1000.00")

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
