import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.agenda.models import Task

pytestmark = pytest.mark.django_db


def test_index(client, folder, task):
    response = client.get("/agenda/")
    assert response.status_code == 200
    response = client.get(reverse("agenda"))
    assert response.status_code == 200
    assertTemplateUsed(response, "agenda/content.html")
    assert response.context["page"] == "agenda"
    assert response.context["folders"]
    assert response.context["show_events"]


def test_toggle_events(client):
    response = client.get("/agenda/")
    assert response.context["show_events"]
    client.get("/agenda/toggle-events")
    response = client.get("/agenda/")
    assert not response.context["show_events"]


def test_activate(client, folder):
    client.get(f"/agenda/{folder.id}/activate")
    folder.refresh_from_db()
    assert folder.active == 1


def test_status(client, task):
    client.get(f"/agenda/{task.id}/complete")
    task.refresh_from_db()
    assert task.status == "Complete"


def test_add_post(client, folder, task_data):
    task_data["title"] = "New title"
    task_data["date_due"] = ""
    task_data["matter_id"] = ""
    task_data["priority"] = ""
    response = client.post("/agenda/add", task_data)
    assert response.status_code == 302
    found = Task.objects.filter(title=task_data["title"]).first()
    assert found


def test_edit_get(client, task):
    response = client.get(f"/agenda/{task.id}/edit")
    assert response.status_code == 200
    assertTemplateUsed(response, "agenda/form.html")


def test_edit_post(client, folder, task):
    data = {
        "folder": folder.id,
        "title": "Finish unit testing",
        "status": "Pending",
    }
    response = client.post(f"/agenda/{task.id}/edit", data)
    assert response.status_code == 302
    found = Task.objects.filter(title="Finish unit testing").exists()
    assert found


def test_clear(client, folder, task):
    response = client.get(f"/agenda/{folder.id}/clear")
    assert response.status_code == 302
    found = Task.objects.filter(pk=folder.id).exists()
    assert not found
