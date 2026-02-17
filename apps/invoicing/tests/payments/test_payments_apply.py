from decimal import Decimal

import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.accounts.models import CustomUser
from apps.activity.time.models import TimeEntry
from apps.invoicing.applications.models import PaymentApplication
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment
from apps.matters.models import Matter, PracticeArea

pytestmark = pytest.mark.django_db


# -----------------------------------------------------------
# Fixtures
# -----------------------------------------------------------
@pytest.fixture
def user():
    user = CustomUser.objects.create(
        username="Ollie", email="ollie@gmail.com", user_rate=100
    )
    user.set_password("clawboy")
    user.save()
    return user


@pytest.fixture
def client(user):
    from django.test import Client

    client = Client()
    client.login(username="Ollie", password="clawboy")
    client.get("/dash/")
    return client


@pytest.fixture
def practice_area():
    return PracticeArea.objects.create(name="General", is_active=True)


@pytest.fixture
def matter(practice_area):
    return Matter.objects.create(
        name="Apply Test Matter",
        work_status="Active",
        status="Open",
        practice_area=practice_area,
    )


@pytest.fixture
def sent_invoice(user, matter):
    """A SENT invoice with $1000 total (2h @ $500/hr)."""
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
        actions="Billable work",
        hours=Decimal("2.0"),
        rate=500,
        comp=False,
        entered=False,
        invoice=invoice,
    )
    return invoice


@pytest.fixture
def sent_invoice_small(user, matter):
    """A second SENT invoice with $200 total (1h @ $200/hr)."""
    invoice = Invoice.objects.create(
        created_by=user,
        matter=matter,
        date_limit="2024-11-30",
        date_issued="2024-11-01",
        status="SENT",
    )
    TimeEntry.objects.create(
        user=user,
        matter=matter,
        date="2024-01-02",
        actions="Small task",
        hours=Decimal("1.0"),
        rate=200,
        comp=False,
        entered=False,
        invoice=invoice,
    )
    return invoice


@pytest.fixture
def payment_1000(matter):
    return Payment.objects.create(
        matter=matter,
        date="2024-12-15",
        amount=Decimal("1000.00"),
        payment_method="CHECK",
    )


@pytest.fixture
def payment_500(matter):
    return Payment.objects.create(
        matter=matter,
        date="2024-12-15",
        amount=Decimal("500.00"),
        payment_method="CARD",
    )


# -----------------------------------------------------------
# payments_apply GET
# -----------------------------------------------------------
class TestPaymentsApplyGet:
    def test_renders_apply_form(self, client, payment_1000, sent_invoice):
        url = reverse("invoicing:payments-apply", args=[payment_1000.id])
        response = client.get(url)
        assert response.status_code == 200
        assertTemplateUsed(response, "invoicing/applications/apply.html")
        assert response.context["source"] == payment_1000
        assert response.context["source_type"] == "payment"

    def test_shows_unpaid_invoices(self, client, payment_1000, sent_invoice):
        url = reverse("invoicing:payments-apply", args=[payment_1000.id])
        response = client.get(url)
        invoice_ids = [d["invoice"].id for d in response.context["invoice_data"]]
        assert sent_invoice.id in invoice_ids

    def test_shows_unapplied_amount(self, client, payment_1000, sent_invoice):
        url = reverse("invoicing:payments-apply", args=[payment_1000.id])
        response = client.get(url)
        assert response.context["amount_unapplied"] == Decimal("1000.00")

    def test_nonexistent_payment_404(self, client):
        url = reverse("invoicing:payments-apply", args=[99999])
        response = client.get(url)
        assert response.status_code == 404


# -----------------------------------------------------------
# payments_apply POST - successful application
# -----------------------------------------------------------
class TestPaymentsApplyPost:
    def test_apply_full_payment_to_invoice(self, client, payment_1000, sent_invoice):
        url = reverse("invoicing:payments-apply", args=[payment_1000.id])
        response = client.post(url, {f"amount_{sent_invoice.id}": "1000.00"})
        assert response.status_code == 204

        app = PaymentApplication.objects.get(payment=payment_1000, invoice=sent_invoice)
        assert app.amount_applied == Decimal("1000.00")

    def test_apply_partial_payment(self, client, payment_500, sent_invoice):
        url = reverse("invoicing:payments-apply", args=[payment_500.id])
        response = client.post(url, {f"amount_{sent_invoice.id}": "500.00"})
        assert response.status_code == 204

        app = PaymentApplication.objects.get(payment=payment_500, invoice=sent_invoice)
        assert app.amount_applied == Decimal("500.00")

        # Invoice should still be SENT (not fully paid)
        sent_invoice.refresh_from_db()
        assert sent_invoice.status == "SENT"

    def test_full_payment_sets_invoice_paid(self, client, payment_1000, sent_invoice):
        url = reverse("invoicing:payments-apply", args=[payment_1000.id])
        client.post(url, {f"amount_{sent_invoice.id}": "1000.00"})

        sent_invoice.refresh_from_db()
        assert sent_invoice.status == "PAID"

    def test_apply_to_multiple_invoices(
        self, client, payment_1000, sent_invoice_small, sent_invoice
    ):
        """Apply a single payment across two invoices."""
        # Smaller invoice is $200, larger is $1000
        # Payment is $1000, apply $200 to small and $800 to large
        url = reverse("invoicing:payments-apply", args=[payment_1000.id])
        response = client.post(
            url,
            {
                f"amount_{sent_invoice_small.id}": "200.00",
                f"amount_{sent_invoice.id}": "800.00",
            },
        )
        assert response.status_code == 204
        assert PaymentApplication.objects.filter(payment=payment_1000).count() == 2

        # Small invoice fully paid
        sent_invoice_small.refresh_from_db()
        assert sent_invoice_small.status == "PAID"

        # Large invoice partially paid, still SENT
        sent_invoice.refresh_from_db()
        assert sent_invoice.status == "SENT"

    def test_empty_amounts_ignored(self, client, payment_1000, sent_invoice):
        """Submitting with blank amounts creates no applications."""
        url = reverse("invoicing:payments-apply", args=[payment_1000.id])
        response = client.post(url, {f"amount_{sent_invoice.id}": ""})
        assert response.status_code == 204
        assert PaymentApplication.objects.count() == 0


# -----------------------------------------------------------
# payments_apply POST - validation errors
# -----------------------------------------------------------
class TestPaymentsApplyValidation:
    def test_negative_amount_rejected(self, client, payment_1000, sent_invoice):
        url = reverse("invoicing:payments-apply", args=[payment_1000.id])
        response = client.post(url, {f"amount_{sent_invoice.id}": "-100.00"})
        assert response.status_code == 400
        assert "errors" in response.context

    def test_zero_amount_rejected(self, client, payment_1000, sent_invoice):
        url = reverse("invoicing:payments-apply", args=[payment_1000.id])
        response = client.post(url, {f"amount_{sent_invoice.id}": "0"})
        assert response.status_code == 400
        assert "errors" in response.context

    def test_exceeds_invoice_remaining(self, client, payment_1000, sent_invoice):
        """Cannot apply more than the invoice's remaining balance."""
        url = reverse("invoicing:payments-apply", args=[payment_1000.id])
        # Invoice is $1000, try to apply $1500
        payment_1000.amount = Decimal("1500.00")
        payment_1000.save()

        response = client.post(url, {f"amount_{sent_invoice.id}": "1500.00"})
        assert response.status_code == 400
        assert any("remaining" in e for e in response.context["errors"])

    def test_exceeds_payment_unapplied(
        self, client, payment_500, sent_invoice, sent_invoice_small
    ):
        """Total applied across invoices cannot exceed payment amount."""
        url = reverse("invoicing:payments-apply", args=[payment_500.id])
        # Payment is $500, try to apply $200 + $400 = $600
        response = client.post(
            url,
            {
                f"amount_{sent_invoice_small.id}": "200.00",
                f"amount_{sent_invoice.id}": "400.00",
            },
        )
        assert response.status_code == 400
        assert any("exceeds" in e for e in response.context["errors"])

    def test_invalid_amount_format(self, client, payment_1000, sent_invoice):
        url = reverse("invoicing:payments-apply", args=[payment_1000.id])
        response = client.post(url, {f"amount_{sent_invoice.id}": "abc"})
        assert response.status_code == 400
        assert any("Invalid" in e for e in response.context["errors"])


# -----------------------------------------------------------
# payments_delete_application
# -----------------------------------------------------------
class TestPaymentsDeleteApplication:
    def test_delete_application(self, client, payment_1000, sent_invoice):
        app = PaymentApplication.objects.create(
            payment=payment_1000,
            invoice=sent_invoice,
            amount_applied=Decimal("1000.00"),
        )
        url = reverse("invoicing:payments-application-delete", args=[app.id])
        response = client.post(url)
        assert response.status_code == 200
        assert not PaymentApplication.objects.filter(pk=app.id).exists()

    def test_delete_reverts_paid_to_sent(
        self, client, payment_1000, payment_500, sent_invoice
    ):
        """Deleting one of two applications reverts PAID to SENT when balance remains."""
        # Apply $500 from first payment
        PaymentApplication.objects.create(
            payment=payment_500,
            invoice=sent_invoice,
            amount_applied=Decimal("500.00"),
        )
        # Apply $500 from second payment to fully pay ($1000 total)
        app2 = PaymentApplication.objects.create(
            payment=payment_1000,
            invoice=sent_invoice,
            amount_applied=Decimal("500.00"),
        )
        sent_invoice.refresh_from_db()
        assert sent_invoice.status == "PAID"

        # Delete the second application — leaves $500 remaining
        url = reverse("invoicing:payments-application-delete", args=[app2.id])
        client.post(url)

        sent_invoice.refresh_from_db()
        assert sent_invoice.status == "SENT"
        assert sent_invoice.amount_remaining == Decimal("500.00")

    def test_delete_nonexistent_application_404(self, client):
        url = reverse("invoicing:payments-application-delete", args=[99999])
        response = client.post(url)
        assert response.status_code == 404

    def test_delete_returns_updated_apply_form(
        self, client, payment_1000, sent_invoice
    ):
        app = PaymentApplication.objects.create(
            payment=payment_1000,
            invoice=sent_invoice,
            amount_applied=Decimal("500.00"),
        )
        url = reverse("invoicing:payments-application-delete", args=[app.id])
        response = client.post(url)

        assertTemplateUsed(response, "invoicing/applications/apply.html")
        assert response.context["amount_unapplied"] == Decimal("1000.00")
