import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.matters.models import Matter

pytestmark = pytest.mark.django_db


def test_index(client, matter):
    response = client.get("/matters/")
    assert response.status_code == 200
    response = client.get(reverse("matters:list"))
    assert response.status_code == 200


def test_detail(client, matter):
    response = client.get(f"/matters/{matter.id}")
    assert response.status_code == 302
    response = client.get(f"/matters/{matter.id}/contacts")
    assertTemplateUsed(response, "matters/contacts/list.html")
    assert response.context["matter"] == matter


def test_add_get(client, folder):
    # test without a selected folder
    response = client.get("/matters/add")
    assert response.status_code == 200
    assertTemplateUsed(response, "matters/form.html")
    assert response.status_code == 200


def test_add_post(client, user, matter_data):
    response = client.post("/matters/add", matter_data)
    assert response.status_code == 200

    found = Matter.objects.filter(name=matter_data["name"]).first()
    assert found


def test_edit_get(client, matter):
    response = client.get(f"/matters/{matter.id}/edit")
    assert response.status_code == 200
    assertTemplateUsed(response, "matters/form.html")


def test_edit_post(client, user, matter):
    data = {
        "user_id": user.id,
        "name": "Sample Test Matter",
        "description": "New description",
        "status": "Open",
        "date_start": "2020-08-07",
        "date_end": "2022-08-07",
        "firm": "Test Firm",
        "clio_matter_no": "123",
        "ref_no": "125",
        "practice_area": "General",
        "client": matter.client.id,
    }
    response = client.post(f"/matters/{matter.id}/edit", data)
    assert response.status_code == 302

    found = Matter.objects.filter(description="New description").exists()
    assert found


def test_delete(client, matter):
    response = client.get(f"/matters/{matter.id}/delete")
    assert response.status_code == 302
    found = Matter.objects.filter(pk=matter.id).exists()
    assert not found


def test_filter_new(client):
    response = client.get("/matters/filter")
    assert response.status_code == 200
    assertTemplateUsed("matters/filter.html")
    assert response.context["filter"]["status"] == "Open"
    assert response.context["filter"]["area"] is None


def test_filter_update(client):
    data = {
        "status": "Open",
        "date_from": "",
        "date_to": "",
        "firm": "Campbell & Brannon",
        "order": "name",
        "area": "CB",
    }
    response = client.post("/matters/filter/update", data)
    assert response.status_code == 302
    response = client.get("/matters/filter")
    assert response.context["filter"]["area"] == "CB"


def test_filter_quick(client):
    response = client.get("/matters/filter/general")
    assert response.status_code == 302
    response = client.get("/matters/filter")
    assert response.context["filter"]["area"] == "General"


def test_filter_order(client):
    response = client.get("/matters/sort/random")
    assert response.status_code == 302
    assert client.session["matters_filter"]["order"] == "random"


def test_edit_description(client, user, matter):
    data = {
        "description": "New edited description",
    }
    response = client.post(f"/matters/{matter.id}/edit-description", data)
    assert response.status_code == 302
    found = Matter.objects.filter(description="New edited description").exists()
    assert found


def test_print(client, matter):
    response = client.get(f"/matters/{matter.id}/print")
    assert response.status_code == 200
    assertTemplateUsed("matters/print.html")
