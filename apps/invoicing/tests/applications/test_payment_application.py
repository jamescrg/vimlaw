from decimal import Decimal

import pytest

from apps.invoicing.applications.models import PaymentApplication
from apps.invoicing.invoices.models import Invoice

pytestmark = pytest.mark.django_db


# -----------------------------------------------------
# PaymentApplication model tests
# -----------------------------------------------------
def test_str(invoice_sent, payment):
    """Test PaymentApplication string representation."""
    app = PaymentApplication.objects.create(
        payment=payment,
        invoice=invoice_sent,
        amount_applied=Decimal("500.00"),
    )
    assert f"${app.amount_applied}" in str(app)
    assert f"Payment #{payment.id}" in str(app)
    assert f"Invoice #{invoice_sent.id}" in str(app)


def test_save_updates_invoice_to_paid_when_fully_applied(invoice_sent, payment):
    """Test that invoice status changes to PAID when fully allocated."""
    assert invoice_sent.status == "SENT"
    invoice_total = invoice_sent.value["final_total"]
    assert invoice_total == Decimal("1000.00")

    PaymentApplication.objects.create(
        payment=payment,
        invoice=invoice_sent,
        amount_applied=invoice_total,
    )

    invoice_sent.refresh_from_db()
    assert invoice_sent.status == "PAID"


def test_save_does_not_update_status_when_partially_applied(
    invoice_sent, payment_partial
):
    """Test that invoice remains SENT when only partially paid."""
    assert invoice_sent.status == "SENT"

    PaymentApplication.objects.create(
        payment=payment_partial,
        invoice=invoice_sent,
        amount_applied=Decimal("500.00"),
    )

    invoice_sent.refresh_from_db()
    assert invoice_sent.status == "SENT"
    assert invoice_sent.amount_remaining == Decimal("500.00")


def test_delete_with_remaining_balance_reverts_to_sent(
    user, matter, payment, payment_partial
):
    """Test that deleting partial application reverts PAID invoice to SENT when balance remains."""
    from apps.activity.time.models import TimeEntry

    invoice = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2025-01-01",
        date_issued="2025-01-01",
        status="SENT",
    )
    TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2025-01-01",
        actions="Work",
        hours=Decimal("2.0"),
        rate=500,
        comp=False,
        invoice=invoice,
    )  # $1000 total

    # Apply $500 from first payment
    PaymentApplication.objects.create(
        payment=payment_partial,
        invoice=invoice,
        amount_applied=Decimal("500.00"),
    )

    # Apply $500 from second payment to fully pay
    app2 = PaymentApplication.objects.create(
        payment=payment,
        invoice=invoice,
        amount_applied=Decimal("500.00"),
    )

    invoice.refresh_from_db()
    assert invoice.status == "PAID"
    assert invoice.amount_remaining == Decimal("0.00")

    # Delete only one application - leaves $500 remaining
    app2.delete()

    invoice.refresh_from_db()
    # Now amount_remaining should be > 0, so status reverts
    assert invoice.amount_remaining == Decimal("500.00")
    assert invoice.status == "SENT"


def test_amount_remaining_calculation(invoice_sent, payment):
    """Test that amount_remaining reflects applied payments."""
    assert invoice_sent.amount_remaining == Decimal("1000.00")

    PaymentApplication.objects.create(
        payment=payment,
        invoice=invoice_sent,
        amount_applied=Decimal("300.00"),
    )

    invoice_sent.refresh_from_db()
    assert invoice_sent.amount_remaining == Decimal("700.00")


def test_multiple_partial_payments(
    user, matter, invoice_sent, payment, payment_partial
):
    """Test applying multiple partial payments to an invoice."""
    # First payment
    PaymentApplication.objects.create(
        payment=payment,
        invoice=invoice_sent,
        amount_applied=Decimal("400.00"),
    )
    invoice_sent.refresh_from_db()
    assert invoice_sent.amount_remaining == Decimal("600.00")
    assert invoice_sent.status == "SENT"

    # Second payment
    PaymentApplication.objects.create(
        payment=payment_partial,
        invoice=invoice_sent,
        amount_applied=Decimal("500.00"),
    )
    invoice_sent.refresh_from_db()
    assert invoice_sent.amount_remaining == Decimal("100.00")
    assert invoice_sent.status == "SENT"
