import pytest
from django.test import Client
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
    assertTemplateUsed(response, "matters/contacts/contact-table.html")
    assert response.context["matter"] == matter


def test_add_get(client, folder):
    # test without a selected folder
    response = client.get("/matters/add")
    assert response.status_code == 200
    assertTemplateUsed(response, "matters/form.html")
    assert response.status_code == 200


def test_add_post(client, user, matter_data):
    # Convert contact object to id for form submission
    matter_data["client"] = matter_data["client"].id
    response = client.post("/matters/add", matter_data)
    assert response.status_code == 204
    found = Matter.objects.filter(name=matter_data["name"]).first()
    assert found


def test_edit_get(client, matter):
    response = client.get(f"/matters/{matter.id}/edit")
    assert response.status_code == 200
    assertTemplateUsed(response, "matters/form.html")


def test_edit_post(client, user, matter):
    data = {
        "name": "Sample Test Matter",
        "description": "Test description",
        "work_status": "New description",
        "status": "Open",
        "date_start": "2020-08-07",
        "practice_area": matter.practice_area.id,
        "client": matter.client.id,
        "billing_type": "HOURLY",
    }
    response = client.post(f"/matters/{matter.id}/edit", data)
    assert response.status_code == 204

    found = Matter.objects.filter(work_status="New description").exists()
    assert found


def test_delete_confirmation(matter, user):
    user.role = "ADMIN"
    user.save()
    admin_client = Client()
    admin_client.login(username="Ollie", password="clawboy")
    admin_client.get("/dash/")
    response = admin_client.get(f"/matters/{matter.id}/delete")
    assert response.status_code == 200

    assertTemplateUsed(response, "matters/delete_confirmation.html")

    found = Matter.objects.filter(pk=matter.id).exists()
    assert found


def test_delete_forbidden_for_non_admin(client, matter):
    response = client.get(f"/matters/{matter.id}/delete")
    assert response.status_code == 403


def test_delete_confirm(matter, user):
    user.role = "ADMIN"
    user.save()
    admin_client = Client()
    admin_client.login(username="Ollie", password="clawboy")
    admin_client.get("/dash/")
    response = admin_client.delete(f"/matters/{matter.id}/delete")
    assert response.status_code == 204

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
        "order": "name",
        "practice_area": "CB",
    }
    response = client.post("/matters/filter", data)
    assert response.status_code == 204
    response = client.get("/matters/filter")
    assert response.context["form"]["practice_area"].value() == "CB"


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


# -----------------------------------------------------
# edge case tests - nonexistent records
# -----------------------------------------------------
def test_detail_nonexistent(client):
    response = client.get("/matters/99999/contacts")
    assert response.status_code == 404


def test_edit_nonexistent(client):
    response = client.get("/matters/99999/edit")
    assert response.status_code == 404


def test_delete_nonexistent(user):
    user.role = "ADMIN"
    user.save()
    admin_client = Client()
    admin_client.login(username="Ollie", password="clawboy")
    admin_client.get("/dash/")
    response = admin_client.delete("/matters/99999/delete")
    assert response.status_code == 404
