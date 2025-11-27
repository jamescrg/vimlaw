from decimal import Decimal

import pytest

from apps.activity.time.models import TimeEntry
from apps.invoicing.applications.models import PaymentApplication
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment

pytestmark = pytest.mark.django_db


# -----------------------------------------------------
# Payment.amount_unapplied property tests
# -----------------------------------------------------
def test_amount_unapplied_no_applications(payment):
    """Test amount_unapplied equals full amount when no applications exist."""
    assert payment.amount_unapplied == payment.amount


def test_amount_unapplied_with_partial_application(user, matter, payment):
    """Test amount_unapplied reflects partial application."""
    # Create invoice
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
        date="2024-01-01",
        actions="Work",
        hours=Decimal("5.0"),
        rate=400,
        comp=False,
        invoice=invoice,
    )

    # Apply $600 of the $1000 payment
    PaymentApplication.objects.create(
        payment=payment,
        invoice=invoice,
        amount_applied=Decimal("600.00"),
    )

    assert payment.amount_unapplied == Decimal("400.00")


def test_amount_unapplied_fully_applied(user, matter, payment):
    """Test amount_unapplied is zero when fully applied."""
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
        date="2024-01-01",
        actions="Work",
        hours=Decimal("5.0"),
        rate=400,
        comp=False,
        invoice=invoice,
    )

    PaymentApplication.objects.create(
        payment=payment,
        invoice=invoice,
        amount_applied=Decimal("1000.00"),
    )

    assert payment.amount_unapplied == Decimal("0.00")


def test_amount_unapplied_multiple_applications(user, matter, payment):
    """Test amount_unapplied with multiple applications to different invoices."""
    # Create two invoices
    invoice1 = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2024-12-31",
        date_issued="2024-12-01",
        status="SENT",
    )
    TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-01-01",
        actions="Work 1",
        hours=Decimal("2.0"),
        rate=300,
        comp=False,
        invoice=invoice1,
    )

    invoice2 = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2024-12-31",
        date_issued="2024-12-15",
        status="SENT",
    )
    TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-01-15",
        actions="Work 2",
        hours=Decimal("2.0"),
        rate=300,
        comp=False,
        invoice=invoice2,
    )

    # Apply $300 to first invoice
    PaymentApplication.objects.create(
        payment=payment,
        invoice=invoice1,
        amount_applied=Decimal("300.00"),
    )

    # Apply $400 to second invoice
    PaymentApplication.objects.create(
        payment=payment,
        invoice=invoice2,
        amount_applied=Decimal("400.00"),
    )

    assert payment.amount_unapplied == Decimal("300.00")  # 1000 - 300 - 400


# -----------------------------------------------------
# Payment.applied_status property tests
# -----------------------------------------------------
def test_applied_status_unapplied(payment):
    """Test applied_status shows Unapplied when no applications."""
    assert payment.applied_status == "Unapplied"


def test_applied_status_partially_applied(user, matter, payment):
    """Test applied_status shows Unapplied when partially applied."""
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
        date="2024-01-01",
        actions="Work",
        hours=Decimal("5.0"),
        rate=400,
        comp=False,
        invoice=invoice,
    )

    PaymentApplication.objects.create(
        payment=payment,
        invoice=invoice,
        amount_applied=Decimal("500.00"),
    )

    assert payment.applied_status == "Unapplied"


def test_applied_status_fully_applied(user, matter, payment):
    """Test applied_status shows Applied when fully applied."""
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
        date="2024-01-01",
        actions="Work",
        hours=Decimal("5.0"),
        rate=400,
        comp=False,
        invoice=invoice,
    )

    PaymentApplication.objects.create(
        payment=payment,
        invoice=invoice,
        amount_applied=Decimal("1000.00"),
    )

    assert payment.applied_status == "Applied"


# -----------------------------------------------------
# Payment.method_display property tests
# -----------------------------------------------------
def test_method_display_card(payment):
    """Test method_display shows Card for CARD payment method (fixture uses CARD)."""
    assert payment.method_display == "Card"


def test_method_display_check(matter):
    """Test method_display shows Check for CHECK payment method."""
    payment = Payment.objects.create(
        matter=matter,
        date="2024-12-15",
        amount=Decimal("500.00"),
        payment_method="CHECK",
    )
    assert payment.method_display == "Check"


def test_method_display_trust(matter):
    """Test method_display shows Trust for TRUST payment method."""
    payment = Payment.objects.create(
        matter=matter,
        date="2024-12-15",
        amount=Decimal("500.00"),
        payment_method="TRUST",
    )
    assert payment.method_display == "Trust"


# -----------------------------------------------------
# Payment str representation
# -----------------------------------------------------
def test_str(payment):
    """Test Payment string representation."""
    assert f"Payment #{payment.id}" in str(payment)
    assert str(payment.matter) in str(payment)
