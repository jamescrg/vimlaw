import pytest
from pytest_django.asserts import assertTemplateUsed

from apps.matters.settlement.models import SettlementEntry

pytestmark = pytest.mark.django_db


def test_index(client, matter, entry):
    response = client.get(f"/matters/{matter.id}/settlement")
    assert response.status_code == 301
    assertTemplateUsed("matters/settlement/list.html")


def test_add_get(client, matter):
    response = client.get(f"/matters/{matter.id}/settlement/add")
    assert response.status_code == 200
    assertTemplateUsed(response, "matters/settlement/form.html")


def test_add_post(client, matter, entry_data):
    response = client.post(f"/matters/{matter.id}/settlement/add", entry_data)
    assert response.status_code == 204
    found = SettlementEntry.objects.filter(amount=entry_data["amount"]).first()
    assert found


def test_edit_get(client, matter, entry):
    response = client.get(f"/matters/{matter.id}/settlement/{entry.id}/edit")
    assert response.status_code == 200
    assertTemplateUsed(response, "matters/settlement/form.html")


def test_edit_post(client, matter, entry):
    data = {
        "date": "2020-08-12",
        "medium": "Call In",
        "type": "Demand",
        "amount": "500000",
        "notes": "With full release",
    }
    response = client.post(f"/matters/{matter.id}/settlement/{entry.id}/edit", data)
    assert response.status_code == 204
    found = SettlementEntry.objects.filter(amount="500000").exists()
    assert found


def test_delete(client, matter, entry):
    response = client.get(f"/matters/{matter.id}/settlement/{entry.id}/delete")
    assert response.status_code == 204
    found = SettlementEntry.objects.filter(pk=entry.id).exists()
    assert not found
