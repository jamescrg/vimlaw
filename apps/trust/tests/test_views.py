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
    response = client.get("/invoicing/trust/history/30days/")
    assert response.status_code == 200
    assertTemplateUsed(response, "trust/history.html")
    assert "interval" in response.context


def test_client(client, contact, transaction):
    response = client.get(f"/invoicing/trust/client/{contact.id}")
    assert response.status_code == 301


def test_add_get(client):
    response = client.get("/invoicing/trust/add")
    assert response.status_code == 200
    assertTemplateUsed(response, "trust/form.html")


def test_add_post(client, transaction_data):
    response = client.post("/invoicing/trust/add", transaction_data)
    assert response.status_code == 204
    found = Transaction.objects.filter(
        description=transaction_data["description"]
    ).first()
    assert found


def test_edit_get(client, transaction):
    response = client.get(f"/invoicing/trust/{transaction.id}/edit")
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
    response = client.post(f"/invoicing/trust/{transaction.id}/edit", data)
    assert response.status_code == 204
    found = Transaction.objects.filter(description="Retainer").exists()
    assert found


def test_delete(client, transaction):
    response = client.get(f"/invoicing/trust/{transaction.id}/delete")
    assert response.status_code == 204
    found = Transaction.objects.filter(pk=transaction.id).exists()
    assert not found


# -----------------------------------------------------
# toggle views
# -----------------------------------------------------
def test_toggle_entered(client, transaction):
    assert not transaction.entered
    # Default session is summary view
    response = client.get(f"/invoicing/trust/{transaction.id}/entered")
    assert response.status_code == 204
    assert response["HX-Trigger"] == "trustChanged"
    transaction.refresh_from_db()
    assert transaction.entered

    # Toggle back
    response = client.get(f"/invoicing/trust/{transaction.id}/entered")
    assert response.status_code == 204
    transaction.refresh_from_db()
    assert not transaction.entered


def test_toggle_confirmed(client, transaction):
    assert not transaction.confirmed
    # Default session is summary view
    response = client.get(f"/invoicing/trust/{transaction.id}/confirmed")
    assert response.status_code == 204
    assert response["HX-Trigger"] == "trustChanged"
    transaction.refresh_from_db()
    assert transaction.confirmed

    # Toggle back
    response = client.get(f"/invoicing/trust/{transaction.id}/confirmed")
    assert response.status_code == 204
    transaction.refresh_from_db()
    assert not transaction.confirmed


def test_toggle_entered_triggers_history_view(client, transaction):
    session = client.session
    session["trust_view"] = "history"
    session.save()
    response = client.get(f"/invoicing/trust/{transaction.id}/entered")
    assert response.status_code == 204
    assert response["HX-Trigger"] == "trustHistoryChanged"


def test_toggle_confirmed_triggers_client_view(client, transaction):
    session = client.session
    session["trust_view"] = "client"
    session.save()
    response = client.get(f"/invoicing/trust/{transaction.id}/confirmed")
    assert response.status_code == 204
    assert response["HX-Trigger"] == "trustClientChanged"


def test_toggle_entered_nonexistent(client):
    response = client.get("/invoicing/trust/99999/entered")
    assert response.status_code == 404


def test_toggle_confirmed_nonexistent(client):
    response = client.get("/invoicing/trust/99999/confirmed")
    assert response.status_code == 404


# -----------------------------------------------------
# edge case tests - nonexistent records
# -----------------------------------------------------
def test_edit_nonexistent(client):
    response = client.get("/invoicing/trust/99999/edit")
    assert response.status_code == 404
