import pytest
from pytest_django.asserts import assertTemplateUsed

from apps.matters.timeline.models import Fact


pytestmark = pytest.mark.django_db


def test_index(client, matter, fact):
    response = client.get(f"/matters/{matter.id}/timeline")
    assert response.status_code == 200
    assertTemplateUsed("matters/timeline/list.html")


def test_add_get(client, matter):
    response = client.get(f"/matters/{matter.id}/timeline/add")
    assert response.status_code == 200
    assertTemplateUsed(response, "matters/timeline/form.html")


def test_add_post(client, matter, fact_data):
    response = client.post(f"/matters/{matter.id}/timeline/add", fact_data)
    assert response.status_code == 302
    found = Fact.objects.filter(description=fact_data["description"]).first()
    assert found


def test_edit_get(client, matter, fact):
    response = client.get(f"/matters/{matter.id}/timeline/{fact.id}/edit")
    assert response.status_code == 200
    assertTemplateUsed(response, "matters/timeline/form.html")


def test_edit_post(client, matter, fact):
    data = {
        "date": "2020-08-07",
        "description": "Purchse of property",
        "citation": "Evidence",
        "emphasis": "No",
    }
    response = client.post(f"/matters/{matter.id}/timeline/{fact.id}/edit", data)
    assert response.status_code == 302
    found = Fact.objects.filter(description="Purchse of property").exists()
    assert found


def test_delete(client, matter, fact):
    response = client.get(f"/matters/{matter.id}/timeline/{fact.id}/delete")
    assert response.status_code == 302
    found = Fact.objects.filter(pk=fact.id).exists()
    assert not found
