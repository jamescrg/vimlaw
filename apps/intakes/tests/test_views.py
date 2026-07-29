import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.intakes.models import Intake, Note
from apps.matters.models import PracticeArea

pytestmark = pytest.mark.django_db


def test_index(client):
    response = client.get("/intakes/")
    assert response.status_code == 200
    response = client.get(reverse("intakes:list"))
    assert response.status_code == 200
    assertTemplateUsed(response, "intakes/list-table.html")
    assert response.context["app"] == "intakes"


def test_detail(client, intake):
    response = client.get(f"/intakes/{intake.id}")
    assert response.status_code == 301


def test_intake_add_get(client):
    response = client.get("/intakes/add")
    assert response.status_code == 200
    assertTemplateUsed(response, "intakes/form.html")
    assert response.context["add"]


def test_intake_add_post(client, intake_data):
    response = client.post("/intakes/add", intake_data)
    assert response.status_code == 204
    found = Intake.objects.filter(name=intake_data["name"]).first()
    assert found


def test_intake_edit_get(client, intake):
    response = client.get(f"/intakes/{intake.id}/edit")
    assert response.status_code == 200
    assertTemplateUsed(response, "intakes/form.html")


def test_intake_edit_post(client, intake, practice_area):
    data = {
        "date": "2020-01-01",
        "name": "Desmond Tutu",
        "address": "225 Paper Street, Porbandar, India",
        "phone": "123.456.7890",
        "email": "tutu@example.com",
        "practice_area": practice_area.id,
        "source": "Internet",
        "status": "Open",
    }
    response = client.post(f"/intakes/{intake.id}/edit", data)
    assert response.status_code == 204
    found = Intake.objects.filter(name="Desmond Tutu").exists()
    assert found


def test_intake_delete(client, intake):
    response = client.get(f"/intakes/{intake.id}/delete")
    assert response.status_code == 302
    found = Intake.objects.filter(pk=intake.id).exists()
    assert not found


def test_filter_new(client):
    response = client.get("/intakes/filter-intakes")
    assert response.status_code == 200
    assertTemplateUsed("intakes/intake-filter.html")


def test_filter_update(client):
    data = {
        "status": "Pending",
        "date_from": "",
        "date_to": "",
        "area": "",
        "order_by": "date",
        "limit": "",
        "source": "",
    }
    response = client.post("/intakes/filter-intakes", data)
    assert response.status_code == 204
    response = client.get("/intakes/filter-intakes")
    assert response.context["form"]["status"].value() == "Pending"


def test_filter_quick(client):
    data = {"order_by": "date"}
    response = client.post("/intakes/filter-intakes", data)
    assert response.status_code == 204
    response = client.get("/intakes/filter-intakes")
    assert response.context["form"]["order_by"].value() == ["date"]


def test_note_add_get(client, intake):
    response = client.get(f"/intakes/{intake.id}/add-note")
    assert response.status_code == 200
    assertTemplateUsed(response, "intakes/form_note.html")
    assert response.context["add"]


def test_note_add_post(client, intake, note_data):
    response = client.post(f"/intakes/{intake.id}/add-note", note_data)
    assert response.status_code == 204
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
    assert response.status_code == 204
    found = Note.objects.filter(type="Boundary Dispute").exists()
    assert found


def test_note_delete(client, note):
    response = client.get(f"/intakes/{note.id}/delete-note")
    assert response.status_code == 204
    found = Note.objects.filter(pk=note.id).exists()
    assert not found


def test_intake_edit_practice_area(client, intake):
    # Create a new practice area to change to
    title_pa = PracticeArea.objects.create(name="Title", is_active=True)
    response = client.post(f"/intakes/edit-practice-area/{intake.id}/{title_pa.id}")
    assert response.status_code == 200
    assertTemplateUsed(response, "intakes/intake-practice-area.html")
    intake.refresh_from_db()
    assert intake.practice_area.name == "Title"


# -----------------------------------------------------
# edge case tests - nonexistent records
# -----------------------------------------------------
def test_intake_edit_nonexistent(client):
    response = client.get("/intakes/99999/edit")
    assert response.status_code == 404


def test_intake_delete_nonexistent(client):
    response = client.get("/intakes/99999/delete")
    assert response.status_code == 404


def test_note_edit_nonexistent(client):
    response = client.get("/intakes/99999/edit-note")
    assert response.status_code == 404


def test_note_delete_nonexistent(client):
    # Note delete uses .filter().delete() which succeeds silently for nonexistent
    response = client.get("/intakes/99999/delete-note")
    assert response.status_code == 204


def test_default_filter_highlights_open_chip(client):
    """First visit seeds the Open default; its quick-filter chip must show
    selected, matching how tasks/time seed filter_label with the default."""
    response = client.get("/intakes/list/")
    assert response.status_code == 200
    content = response.content.decode()
    open_chip = content.split('hx-post="/intakes/quick-filter-status/Open"')[0]
    assert "toggle-active" in open_chip.rsplit("quick-status", 1)[1]
