import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.intakes.models import Intake, Note

pytestmark = pytest.mark.django_db


def test_index(client):
    response = client.get("/intakes/")
    assert response.status_code == 200
    response = client.get(reverse("intakes-list"))
    assert response.status_code == 200
    assertTemplateUsed(response, "intakes/list.html")
    assert response.context["page"] == "intakes"


def test_detail(client, intake):
    response = client.get(f"/intakes/{intake.id}")
    assert response.status_code == 200
    assertTemplateUsed(response, "intakes/detail.html")
    assert response.context["intake"] == intake


def test_intake_add_get(client):
    response = client.get("/intakes/add")
    assert response.status_code == 200
    assertTemplateUsed(response, "intakes/form.html")
    assert response.context["add"]


def test_intake_add_post(client, intake_data):
    response = client.post("/intakes/add", intake_data)
    assert response.status_code == 302
    found = Intake.objects.filter(name=intake_data["name"]).first()
    assert found


def test_intake_edit_get(client, intake):
    response = client.get(f"/intakes/{intake.id}/edit")
    assert response.status_code == 200
    assertTemplateUsed(response, "intakes/form.html")


def test_intake_edit_post(client, intake):
    data = {
        "date": "2020-01-01",
        "name": "Desmond Tutu",
        "address": "225 Paper Street, Porbandar, India",
        "phone": "123.456.7890",
        "email": "tutu@gandhi.com",
        "practice_area": "General",
        "source": "Internet",
        "status": "Open",
    }
    response = client.post(f"/intakes/{intake.id}/edit", data)
    assert response.status_code == 302
    found = Intake.objects.filter(name="Desmond Tutu").exists()
    assert found


def test_intake_delete(client, intake):
    response = client.get(f"/intakes/{intake.id}/delete")
    assert response.status_code == 302
    found = Intake.objects.filter(pk=intake.id).exists()
    assert not found


def test_filter_new(client):
    response = client.get("/intakes/filter")
    assert response.status_code == 200
    assertTemplateUsed("intakes/filter.html")
    assert response.context["filter"]["status"] == "Open"
    assert response.context["filter"]["area"] is None


def test_filter_update(client):
    data = {
        "status": "Pending",
        "date_from": "",
        "date_to": "",
        "area": "",
        "order": "date",
        "limit": "",
        "source": "",
    }
    response = client.post("/intakes/filter/update", data)
    assert response.status_code == 302
    response = client.get("/intakes/filter")
    assert response.context["filter"]["status"] == "Pending"


def test_filter_quick(client):
    response = client.get("/intakes/filter/recent")
    assert response.status_code == 302
    response = client.get("/intakes/filter")
    assert response.context["filter"]["order"] == "date"


def test_filter_order(client):
    response = client.get("/intakes/sort/date")
    assert response.status_code == 302
    assert True


def test_note_add_get(client, intake):
    response = client.get(f"/intakes/{intake.id}/add-note")
    assert response.status_code == 200
    assertTemplateUsed(response, "intakes/form_note.html")
    assert response.context["add"]


def test_note_add_post(client, intake, note_data):
    response = client.post(f"/intakes/{intake.id}/add-note", note_data)
    assert response.status_code == 302
    found = Note.objects.filter(intake=intake).first()
    assert found


def test_note_edit_get(client, note):
    response = client.get(f"/intakes/{note.id}/edit-note")
    assert response.status_code == 200
    assertTemplateUsed(response, "intakes/form_note.html")


def test_note_edit_post(client, user, intake, note):
    data = {
        "user": user.id,
        "intake": intake.id,
        "date": "2022-12-28",
        "time": "00:00",
        "type": "Boundary Dispute",
        "details": "",
    }
    response = client.post(f"/intakes/{note.id}/edit-note", data)
    assert response.status_code == 302
    found = Note.objects.filter(type="Boundary Dispute").exists()
    assert found


def test_note_delete(client, note):
    response = client.get(f"/intakes/{note.id}/delete-note")
    assert response.status_code == 302
    found = Note.objects.filter(pk=note.id).exists()
    assert not found
