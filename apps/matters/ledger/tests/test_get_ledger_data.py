from decimal import Decimal

import pytest

from apps.invoicing.credits.models import Credit
from apps.invoicing.invoices.models import Invoice
from apps.matters.ledger.get_ledger_data import get_ledger_data

pytestmark = pytest.mark.django_db


class TestGetLedgerDataEmpty:
    def test_empty_matter(self, matter):
        result = get_ledger_data(matter)
        assert result["transactions"] == []
        assert result["balance_due"] == 0
        assert result["total_credits"] == 0


class TestGetLedgerDataInvoiceFiltering:
    def test_excludes_draft_invoices(self, matter, draft_invoice):
        result = get_ledger_data(matter)
        descriptions = [t["description"] for t in result["transactions"]]
        assert f"Invoice {draft_invoice.id}" not in descriptions

    def test_includes_sent_invoices(self, matter, sent_invoice):
        result = get_ledger_data(matter)
        descriptions = [t["description"] for t in result["transactions"]]
        assert f"Invoice {sent_invoice.id}" in descriptions

    def test_excludes_approved_invoices(self, user, matter):
        invoice = Invoice.objects.create(
            created_by=user,
            matter=matter,
            date_limit="2024-04-30",
            date_issued="2024-04-01",
            status="APPROVED",
        )
        result = get_ledger_data(matter)
        descriptions = [t["description"] for t in result["transactions"]]
        assert f"Invoice {invoice.id}" not in descriptions

    def test_includes_paid_invoices(self, user, matter):
        invoice = Invoice.objects.create(
            created_by=user,
            matter=matter,
            date_limit="2024-03-31",
            date_issued="2024-03-01",
            status="PAID",
        )
        result = get_ledger_data(matter)
        descriptions = [t["description"] for t in result["transactions"]]
        assert f"Invoice {invoice.id}" in descriptions

    def test_includes_deferred_invoices(self, user, matter):
        invoice = Invoice.objects.create(
            created_by=user,
            matter=matter,
            date_limit="2024-02-28",
            date_issued="2024-02-01",
            status="DEFERRED",
        )
        result = get_ledger_data(matter)
        descriptions = [t["description"] for t in result["transactions"]]
        assert f"Invoice {invoice.id}" in descriptions


class TestGetLedgerDataTransactionTypes:
    def test_invoice_is_charge(self, matter, sent_invoice):
        result = get_ledger_data(matter)
        invoice_txn = [
            t for t in result["transactions"] if t["transaction_type"] == "Charge"
        ]
        assert len(invoice_txn) == 1
        assert invoice_txn[0]["amount"] == Decimal("1000.00")

    def test_payment_is_credit(self, matter, sent_invoice, payment):
        result = get_ledger_data(matter)
        credit_txns = [
            t for t in result["transactions"] if t["description"].startswith("Payment")
        ]
        assert len(credit_txns) == 1
        assert credit_txns[0]["transaction_type"] == "Credit"
        assert credit_txns[0]["amount"] == Decimal("400.00")

    def test_credit_is_credit(self, matter, sent_invoice, credit):
        result = get_ledger_data(matter)
        credit_txns = [
            t for t in result["transactions"] if t["description"] == "Courtesy credit"
        ]
        assert len(credit_txns) == 1
        assert credit_txns[0]["transaction_type"] == "Credit"


class TestGetLedgerDataRunningBalance:
    def test_single_invoice_balance(self, matter, sent_invoice):
        result = get_ledger_data(matter)
        assert result["balance_due"] == Decimal("1000.00")
        assert result["transactions"][-1]["balance"] == Decimal("1000.00")

    def test_invoice_minus_payment(self, matter, sent_invoice, payment):
        result = get_ledger_data(matter)
        # Invoice $1000 - payment $400 = $600
        assert result["balance_due"] == Decimal("600.00")

    def test_invoice_minus_payment_minus_credit(
        self, matter, sent_invoice, payment, credit
    ):
        result = get_ledger_data(matter)
        # Invoice $1000 - payment $400 - credit $100 = $500
        assert result["balance_due"] == Decimal("500.00")

    def test_running_balance_per_transaction(
        self, matter, sent_invoice, payment, credit
    ):
        """Each transaction should have its own running balance."""
        result = get_ledger_data(matter)
        txns = result["transactions"]
        # Sorted by date: invoice 2024-06-01, payment 2024-07-01, credit 2024-07-15
        # Within same date, charges before credits (sorted by transaction_type)
        assert txns[0]["transaction_type"] == "Charge"
        assert txns[0]["balance"] == Decimal("1000.00")
        # Payment and credit are both "Credit" type, sorted by date
        assert txns[1]["balance"] == Decimal("600.00")
        assert txns[2]["balance"] == Decimal("500.00")


class TestGetLedgerDataSorting:
    def test_sorted_by_date(self, user, matter, sent_invoice, payment, credit):
        result = get_ledger_data(matter)
        dates = [t["date"] for t in result["transactions"]]
        assert dates == sorted(dates)


class TestGetLedgerDataTotalCredits:
    def test_total_credits_with_no_credits(self, matter, sent_invoice):
        result = get_ledger_data(matter)
        assert result["total_credits"] == 0

    def test_total_credits_sums_credits(self, matter, sent_invoice, credit):
        Credit.objects.create(
            matter=matter,
            date="2024-08-01",
            amount=Decimal("50.00"),
            detail="Second credit",
        )
        result = get_ledger_data(matter)
        assert result["total_credits"] == Decimal("150.00")
