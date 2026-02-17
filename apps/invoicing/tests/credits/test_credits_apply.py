from decimal import Decimal

import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.invoicing.applications.models import CreditApplication

pytestmark = pytest.mark.django_db


# -----------------------------------------------------------
# credits_apply GET
# -----------------------------------------------------------
class TestCreditsApplyGet:
    def test_renders_apply_form(self, client, credit, sent_invoice):
        url = reverse("invoicing:credits-apply", args=[credit.id])
        response = client.get(url)
        assert response.status_code == 200
        assertTemplateUsed(response, "invoicing/applications/apply.html")
        assert response.context["source"] == credit
        assert response.context["source_type"] == "credit"

    def test_shows_unpaid_invoices(self, client, credit, sent_invoice):
        url = reverse("invoicing:credits-apply", args=[credit.id])
        response = client.get(url)
        invoice_ids = [d["invoice"].id for d in response.context["invoice_data"]]
        assert sent_invoice.id in invoice_ids

    def test_shows_unapplied_amount(self, client, credit, sent_invoice):
        url = reverse("invoicing:credits-apply", args=[credit.id])
        response = client.get(url)
        assert response.context["amount_unapplied"] == Decimal("1000.00")

    def test_nonexistent_credit_404(self, client):
        url = reverse("invoicing:credits-apply", args=[99999])
        response = client.get(url)
        assert response.status_code == 404


# -----------------------------------------------------------
# credits_apply POST - successful application
# -----------------------------------------------------------
class TestCreditsApplyPost:
    def test_apply_full_credit(self, client, credit, sent_invoice):
        url = reverse("invoicing:credits-apply", args=[credit.id])
        response = client.post(url, {f"amount_{sent_invoice.id}": "1000.00"})
        assert response.status_code == 204

        app = CreditApplication.objects.get(credit=credit, invoice=sent_invoice)
        assert app.amount_applied == Decimal("1000.00")

    def test_apply_partial_credit(self, client, credit, sent_invoice):
        url = reverse("invoicing:credits-apply", args=[credit.id])
        response = client.post(url, {f"amount_{sent_invoice.id}": "400.00"})
        assert response.status_code == 204

        # Invoice still SENT (not fully paid)
        sent_invoice.refresh_from_db()
        assert sent_invoice.status == "SENT"

    def test_full_credit_sets_invoice_paid(self, client, credit, sent_invoice):
        url = reverse("invoicing:credits-apply", args=[credit.id])
        client.post(url, {f"amount_{sent_invoice.id}": "1000.00"})

        sent_invoice.refresh_from_db()
        assert sent_invoice.status == "PAID"

    def test_apply_to_multiple_invoices(
        self, client, credit, sent_invoice, sent_invoice_small
    ):
        url = reverse("invoicing:credits-apply", args=[credit.id])
        response = client.post(
            url,
            {
                f"amount_{sent_invoice_small.id}": "200.00",
                f"amount_{sent_invoice.id}": "800.00",
            },
        )
        assert response.status_code == 204
        assert CreditApplication.objects.filter(credit=credit).count() == 2

        sent_invoice_small.refresh_from_db()
        assert sent_invoice_small.status == "PAID"

        sent_invoice.refresh_from_db()
        assert sent_invoice.status == "SENT"

    def test_empty_amounts_ignored(self, client, credit, sent_invoice):
        url = reverse("invoicing:credits-apply", args=[credit.id])
        response = client.post(url, {f"amount_{sent_invoice.id}": ""})
        assert response.status_code == 204
        assert CreditApplication.objects.count() == 0


# -----------------------------------------------------------
# credits_apply POST - validation errors
# -----------------------------------------------------------
class TestCreditsApplyValidation:
    def test_negative_amount_rejected(self, client, credit, sent_invoice):
        url = reverse("invoicing:credits-apply", args=[credit.id])
        response = client.post(url, {f"amount_{sent_invoice.id}": "-50.00"})
        assert response.status_code == 400
        assert "errors" in response.context

    def test_zero_amount_rejected(self, client, credit, sent_invoice):
        url = reverse("invoicing:credits-apply", args=[credit.id])
        response = client.post(url, {f"amount_{sent_invoice.id}": "0"})
        assert response.status_code == 400

    def test_exceeds_invoice_remaining(self, client, credit, sent_invoice):
        # Credit is $1000, invoice is $1000, bump credit so we can try overapplying
        credit.amount = Decimal("1500.00")
        credit.save()
        url = reverse("invoicing:credits-apply", args=[credit.id])
        response = client.post(url, {f"amount_{sent_invoice.id}": "1500.00"})
        assert response.status_code == 400
        assert any("remaining" in e for e in response.context["errors"])

    def test_exceeds_credit_unapplied(
        self, client, credit, sent_invoice, sent_invoice_small
    ):
        """Total applied across invoices cannot exceed credit amount."""
        # Credit is $1000, try $200 + $900 = $1100
        credit.amount = Decimal("500.00")
        credit.save()
        url = reverse("invoicing:credits-apply", args=[credit.id])
        response = client.post(
            url,
            {
                f"amount_{sent_invoice_small.id}": "200.00",
                f"amount_{sent_invoice.id}": "400.00",
            },
        )
        assert response.status_code == 400
        assert any("exceeds" in e for e in response.context["errors"])

    def test_invalid_amount_format(self, client, credit, sent_invoice):
        url = reverse("invoicing:credits-apply", args=[credit.id])
        response = client.post(url, {f"amount_{sent_invoice.id}": "xyz"})
        assert response.status_code == 400
        assert any("Invalid" in e for e in response.context["errors"])


# -----------------------------------------------------------
# credits_delete_application
# -----------------------------------------------------------
class TestCreditsDeleteApplication:
    def test_delete_application(self, client, credit, sent_invoice):
        app = CreditApplication.objects.create(
            credit=credit,
            invoice=sent_invoice,
            amount_applied=Decimal("1000.00"),
        )
        url = reverse("invoicing:credits-application-delete", args=[app.id])
        response = client.post(url)
        assert response.status_code == 200
        assert not CreditApplication.objects.filter(pk=app.id).exists()

    def test_delete_reverts_paid_to_sent(self, client, credit, sent_invoice, matter):
        """Deleting one of two applications reverts PAID to SENT when balance remains."""
        from apps.invoicing.credits.models import Credit

        credit2 = Credit.objects.create(
            matter=matter,
            date="2024-12-16",
            amount=Decimal("500.00"),
            detail="Second credit",
        )
        # Apply $500 from first credit
        CreditApplication.objects.create(
            credit=credit,
            invoice=sent_invoice,
            amount_applied=Decimal("500.00"),
        )
        # Apply $500 from second credit to fully pay ($1000 total)
        app2 = CreditApplication.objects.create(
            credit=credit2,
            invoice=sent_invoice,
            amount_applied=Decimal("500.00"),
        )
        sent_invoice.refresh_from_db()
        assert sent_invoice.status == "PAID"

        # Delete the second application — leaves $500 remaining
        url = reverse("invoicing:credits-application-delete", args=[app2.id])
        client.post(url)

        sent_invoice.refresh_from_db()
        assert sent_invoice.status == "SENT"
        assert sent_invoice.amount_remaining == Decimal("500.00")

    def test_delete_nonexistent_application_404(self, client):
        url = reverse("invoicing:credits-application-delete", args=[99999])
        response = client.post(url)
        assert response.status_code == 404

    def test_delete_returns_updated_apply_form(self, client, credit, sent_invoice):
        app = CreditApplication.objects.create(
            credit=credit,
            invoice=sent_invoice,
            amount_applied=Decimal("500.00"),
        )
        url = reverse("invoicing:credits-application-delete", args=[app.id])
        response = client.post(url)

        assertTemplateUsed(response, "invoicing/applications/apply.html")
        assert response.context["amount_unapplied"] == Decimal("1000.00")
