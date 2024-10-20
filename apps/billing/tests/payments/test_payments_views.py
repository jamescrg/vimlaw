import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.billing.payments.forms import PaymentForm
from apps.billing.payments.models import Payment

pytestmark = pytest.mark.django_db


def test_payments_list(client, payment):
    response = client.get(reverse("billing:payments-list"))
    assert response.status_code == 200

    assertTemplateUsed(response, "billing/payments/list.html")

    assert response.context["app"] == "billing"
    assert response.context["subapp"] == "payments"


def test_payments_add_get(client):
    response = client.get(reverse("billing:payments-add"))
    assert response.status_code == 200

    assertTemplateUsed(response, "billing/payments/form.html")
    assert isinstance(response.context["form"], PaymentForm)


def test_payments_add_post(client, matter):
    payment_data = {
        "matter": matter.id,
        "date": "2023-01-01",
        "amount": 100,
        "payment_method": "CARD",
    }
    response = client.post(reverse("billing:payments-add"), payment_data)

    assert response.status_code == 204

    assert Payment.objects.filter(matter=matter).exists()


def test_payments_delete(client, payment):
    response = client.post(
        reverse("billing:payments-delete", kwargs={"pk": payment.pk})
    )

    assert response.status_code == 204

    assert not Payment.objects.filter(pk=payment.pk).exists()


def test_payments_edit_get(client, payment):
    response = client.get(reverse("billing:payments-edit", kwargs={"pk": payment.pk}))

    assert response.status_code == 200
    assertTemplateUsed(response, "billing/payments/edit.html")

    assert isinstance(response.context["form"], PaymentForm)
    assert "payment" in response.context


def test_payments_edit_post(client, payment):
    updated_data = {
        "matter": payment.matter.id,
        "date": "2024-05-01",
        "amount": 200,
        "payment_method": "CARD",
    }
    response = client.post(
        reverse("billing:payments-edit", kwargs={"pk": payment.pk}), updated_data
    )
    assert response.status_code == 204

    payment.refresh_from_db()
    assert payment.amount == 200.00


def test_payments_filter_get(client):
    response = client.get(reverse("billing:payments-filter"))
    assert response.status_code == 200

    assertTemplateUsed(response, "billing/payments/filter.html")
    assert "filter" in response.context


def test_payments_filter_post(client):
    filter_data = {"payment_method": "BANK_TRANSFER"}
    response = client.post(reverse("billing:payments-filter"), filter_data)

    assert response.status_code == 204
