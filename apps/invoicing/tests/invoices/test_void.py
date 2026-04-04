from decimal import Decimal

import pytest
from django.urls import reverse

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.invoicing.applications.models import CreditApplication, PaymentApplication
from apps.invoicing.credits.models import Credit
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment

pytestmark = pytest.mark.django_db


# -----------------------------------------------------
# Fixtures
# -----------------------------------------------------


@pytest.fixture
def sent_invoice(user, matter):
    """A SENT invoice with time and expense entries."""
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
        date="2024-01-07",
        actions="Billable work",
        hours=Decimal("2.0"),
        rate=300,
        comp=False,
        entered=False,
        invoice=invoice,
    )
    ExpenseEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-01-07",
        category="Filing Fee",
        description="Court filing",
        amount=Decimal("150.00"),
        comp=False,
        entered=False,
        invoice=invoice,
    )
    return invoice


@pytest.fixture
def sent_invoice_with_payment(sent_invoice, matter):
    """A SENT invoice with a payment applied."""
    payment = Payment.objects.create(
        matter=matter,
        date="2024-12-15",
        amount=Decimal("300.00"),
        payment_method="CHECK",
    )
    PaymentApplication.objects.create(
        payment=payment,
        invoice=sent_invoice,
        amount_applied=Decimal("300.00"),
    )
    return sent_invoice


@pytest.fixture
def sent_invoice_with_credit(sent_invoice, matter):
    """A SENT invoice with a credit applied."""
    credit = Credit.objects.create(
        matter=matter,
        date="2024-12-15",
        amount=Decimal("100.00"),
        detail="Client credit",
    )
    CreditApplication.objects.create(
        credit=credit,
        invoice=sent_invoice,
        amount_applied=Decimal("100.00"),
    )
    return sent_invoice


# -----------------------------------------------------
# void() model method tests
# -----------------------------------------------------


def test_void_sets_status(sent_invoice):
    sent_invoice.void()
    assert sent_invoice.status == "VOID"

    sent_invoice.refresh_from_db()
    assert sent_invoice.status == "VOID"


def test_void_releases_time_entries(sent_invoice):
    assert TimeEntry.objects.filter(invoice=sent_invoice).count() == 1

    sent_invoice.void()

    assert TimeEntry.objects.filter(invoice=sent_invoice).count() == 0
    assert (
        TimeEntry.objects.filter(
            invoice__isnull=True, matter=sent_invoice.matter
        ).count()
        == 1
    )


def test_void_releases_expense_entries(sent_invoice):
    assert ExpenseEntry.objects.filter(invoice=sent_invoice).count() == 1

    sent_invoice.void()

    assert ExpenseEntry.objects.filter(invoice=sent_invoice).count() == 0
    assert (
        ExpenseEntry.objects.filter(
            invoice__isnull=True, matter=sent_invoice.matter
        ).count()
        == 1
    )


def test_void_removes_payment_applications(sent_invoice_with_payment):
    assert (
        PaymentApplication.objects.filter(invoice=sent_invoice_with_payment).count()
        == 1
    )

    sent_invoice_with_payment.void()

    assert (
        PaymentApplication.objects.filter(invoice=sent_invoice_with_payment).count()
        == 0
    )


def test_void_removes_credit_applications(sent_invoice_with_credit):
    assert (
        CreditApplication.objects.filter(invoice=sent_invoice_with_credit).count() == 1
    )

    sent_invoice_with_credit.void()

    assert (
        CreditApplication.objects.filter(invoice=sent_invoice_with_credit).count() == 0
    )


def test_void_payment_remains_unapplied(sent_invoice_with_payment, matter):
    payment = Payment.objects.get(matter=matter)

    sent_invoice_with_payment.void()

    payment.refresh_from_db()
    assert payment.amount == Decimal("300.00")
    assert payment.amount_unapplied == Decimal("300.00")


def test_void_amount_remaining_is_zero(sent_invoice):
    assert sent_invoice.amount_remaining > 0

    sent_invoice.void()

    assert sent_invoice.amount_remaining == 0


def test_void_value_returns_zeros(sent_invoice):
    assert sent_invoice.value["final_total"] > 0

    sent_invoice.void()

    value = sent_invoice.value
    assert value["gross_fees"] == 0
    assert value["gross_expenses"] == 0
    assert value["final_total"] == 0


def test_void_invoice_preserved_in_db(sent_invoice):
    pk = sent_invoice.pk

    sent_invoice.void()

    assert Invoice.objects.filter(pk=pk).exists()


def test_void_released_entries_available_for_new_invoice(user, matter, sent_invoice):
    sent_invoice.void()

    new_invoice = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2025-12-31",
        date_issued="2025-01-01",
    )

    assert TimeEntry.objects.filter(invoice=new_invoice).count() == 1
    assert ExpenseEntry.objects.filter(invoice=new_invoice).count() == 1


# -----------------------------------------------------
# save() guard tests
# -----------------------------------------------------


def test_save_only_captures_entries_for_draft(user, matter):
    """Non-DRAFT invoices should not capture new unbilled entries on save."""
    TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-06-01",
        actions="Unbilled work",
        hours=Decimal("1.0"),
        rate=200,
        comp=False,
        entered=False,
    )

    invoice = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2024-12-31",
        date_issued="2024-12-01",
        status="SENT",
    )

    assert TimeEntry.objects.filter(invoice=invoice).count() == 0


def test_save_captures_entries_for_draft(user, matter):
    """DRAFT invoices should capture unbilled entries on save."""
    TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-06-01",
        actions="Unbilled work",
        hours=Decimal("1.0"),
        rate=200,
        comp=False,
        entered=False,
    )

    invoice = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2024-12-31",
        date_issued="2024-12-01",
    )

    assert TimeEntry.objects.filter(invoice=invoice).count() == 1


# -----------------------------------------------------
# View tests - delete restrictions
# -----------------------------------------------------


def test_delete_draft_allowed(client, invoice):
    """DRAFT invoices can be deleted."""
    response = client.post(
        reverse("invoicing:invoices-delete", kwargs={"pk": invoice.pk})
    )
    assert response.status_code == 302
    assert not Invoice.objects.filter(pk=invoice.pk).exists()


def test_delete_approved_allowed(client, user, matter, entry):
    """APPROVED invoices can be deleted."""
    invoice = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2024-12-31",
        date_issued="2024-12-01",
        status="APPROVED",
    )
    response = client.post(
        reverse("invoicing:invoices-delete", kwargs={"pk": invoice.pk})
    )
    assert response.status_code == 302
    assert not Invoice.objects.filter(pk=invoice.pk).exists()


def test_delete_sent_forbidden(client, sent_invoice):
    """SENT invoices cannot be deleted."""
    response = client.post(
        reverse("invoicing:invoices-delete", kwargs={"pk": sent_invoice.pk})
    )
    assert response.status_code == 403
    assert Invoice.objects.filter(pk=sent_invoice.pk).exists()


def test_delete_paid_forbidden(client, user, matter, entry):
    """PAID invoices cannot be deleted."""
    invoice = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2024-12-31",
        date_issued="2024-12-01",
        status="PAID",
    )
    response = client.post(
        reverse("invoicing:invoices-delete", kwargs={"pk": invoice.pk})
    )
    assert response.status_code == 403
    assert Invoice.objects.filter(pk=invoice.pk).exists()


# -----------------------------------------------------
# View tests - void action
# -----------------------------------------------------


def test_void_confirm_renders(client, sent_invoice):
    response = client.get(
        reverse("invoicing:invoices-void-confirm", kwargs={"pk": sent_invoice.pk})
    )
    assert response.status_code == 200


def test_void_sent_invoice(client, sent_invoice):
    response = client.post(
        reverse("invoicing:invoices-void", kwargs={"pk": sent_invoice.pk})
    )
    assert response.status_code == 204

    sent_invoice.refresh_from_db()
    assert sent_invoice.status == "VOID"


def test_void_paid_invoice(client, user, matter, entry):
    invoice = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2024-12-31",
        date_issued="2024-12-01",
        status="PAID",
    )
    response = client.post(
        reverse("invoicing:invoices-void", kwargs={"pk": invoice.pk})
    )
    assert response.status_code == 204

    invoice.refresh_from_db()
    assert invoice.status == "VOID"


def test_void_draft_rejected(client, invoice):
    """DRAFT invoices should be deleted, not voided."""
    response = client.post(
        reverse("invoicing:invoices-void", kwargs={"pk": invoice.pk})
    )
    assert response.status_code == 400

    invoice.refresh_from_db()
    assert invoice.status == "DRAFT"


def test_void_approved_rejected(client, user, matter, entry):
    """APPROVED invoices should be deleted, not voided."""
    invoice = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2024-12-31",
        date_issued="2024-12-01",
        status="APPROVED",
    )
    response = client.post(
        reverse("invoicing:invoices-void", kwargs={"pk": invoice.pk})
    )
    assert response.status_code == 400


# -----------------------------------------------------
# View tests - edit/status restrictions on VOID
# -----------------------------------------------------


def test_edit_void_invoice_blocked(client, sent_invoice):
    sent_invoice.void()

    response = client.get(
        reverse("invoicing:invoices-edit", kwargs={"pk": sent_invoice.pk})
    )
    assert response.status_code == 403


def test_edit_status_void_invoice_blocked(client, sent_invoice):
    sent_invoice.void()

    response = client.post(
        reverse(
            "invoicing:invoices-edit-status",
            kwargs={"pk": sent_invoice.pk, "status": "SENT", "view": "list"},
        )
    )
    assert response.status_code == 400

    sent_invoice.refresh_from_db()
    assert sent_invoice.status == "VOID"


def test_ledes_void_invoice_blocked(client, sent_invoice):
    sent_invoice.void()

    response = client.get(
        reverse("invoicing:invoice-ledes", kwargs={"pk": sent_invoice.pk})
    )
    assert response.status_code == 400
