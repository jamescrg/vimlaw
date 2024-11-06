import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.trust.models import Transaction

pytestmark = pytest.mark.django_db


def test_index(client):
    response = client.get(reverse("trust:trust"))
    assert response.status_code == 200
    assertTemplateUsed(response, "trust/summary.html")
    assert "confirmed_account_balance" in response.context


def test_history(client, transaction):
    response = client.get("/trust/history/30days/")
    assert response.status_code == 200
    assertTemplateUsed(response, "trust/history.html")
    assert "interval" in response.context


def test_client(client, contact, transaction):
    response = client.get(f"/trust/client/{contact.id}")
    assert response.status_code == 301


def test_add_get(client):
    response = client.get("/trust/add")
    assert response.status_code == 200
    assertTemplateUsed(response, "trust/form.html")


def test_add_post(client, transaction_data):
    response = client.post("/trust/add", transaction_data)
    assert response.status_code == 204
    found = Transaction.objects.filter(
        description=transaction_data["description"]
    ).first()
    assert found


def test_edit_get(client, transaction):
    response = client.get(f"/trust/{transaction.id}/edit")
    assert response.status_code == 200
    assertTemplateUsed(response, "trust/form.html")


def test_edit_post(client, transaction, contact):
    data = {
        "contact": contact.id,
        "date": "2022-12-29",
        "type": "Deposit",
        "description": "Retainer",
        "amount": 2000.00,
        "entered": 0,
        "confirmed": 0,
    }
    response = client.post(f"/trust/{transaction.id}/edit", data)
    assert response.status_code == 200
    found = Transaction.objects.filter(description="Retainer").exists()
    assert found


def test_delete(client, transaction):
    response = client.get(f"/trust/{transaction.id}/delete")
    assert response.status_code == 204
    found = Transaction.objects.filter(pk=transaction.id).exists()
    assert not found
