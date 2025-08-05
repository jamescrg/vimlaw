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
        "clio_matter_id": "123",
        "client_reference_id": "125",
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


def test_filter_update(client):
    data = {
        "status": "Open",
        "date_from": "",
        "date_to": "",
        "firm": "Campbell & Brannon",
        "order": "name",
        "practice_area": "CB",
    }
    response = client.post("/matters/filter", data)
    assert response.status_code == 204
    response = client.get("/matters/filter")
    assert response.context["form"]["practice_area"].value() == "CB"


# def test_filter_quick(client):
# response = client.get("/matters/filter-quick/open")
# breakpoint()
# assert response.status_code == 301
# response = client.get("/matters/")
# assert all([matter.status == "Open" for matter in response.context["matters"]])


def test_filter_order(client):
    response = client.get("/matters/order-by/name")
    assert response.status_code == 204
    assert client.session["matter_filter"]["order_by"] == "name"


def test_edit_work_status(client, user, matter):
    data = {
        "work_status": "New edited work status",
    }
    response = client.post(f"/matters/edit-work-status/{matter.id}", data)
    assert response.status_code == 200


def test_print(client, matter):
    response = client.get(f"/matters/{matter.id}/print")
    assert response.status_code == 200
    assertTemplateUsed("matters/print.html")
