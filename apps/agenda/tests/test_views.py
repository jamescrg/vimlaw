import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.agenda.models import Task

pytestmark = pytest.mark.django_db


def test_index(client, folder, task, matter):
    response = client.get("/agenda/")
    assert response.status_code == 200
    response = client.get(reverse("agenda:agenda"))
    assert response.status_code == 200
    assertTemplateUsed(response, "agenda/content.html")
    assert response.context["page"] == "agenda"
    assert response.context["show_events"]


def test_toggle_events(client):
    response = client.get("/agenda/")
    assert response.context["show_events"]
    client.get("/agenda/toggle-events")
    response = client.get("/agenda/")
    assert not response.context["show_events"]


def test_add_post(client, folder, task_data):
    task_data["description"] = "New title"
    task_data["date_due"] = ""
    task_data["matter_id"] = ""
    task_data["priority"] = ""
    response = client.post("/agenda/add", task_data)
    assert response.status_code == 302
    found = Task.objects.filter(description=task_data["description"]).first()
    assert found


def test_edit_get(client, task):
    response = client.get(f"/agenda/{task.id}/edit")
    assert response.status_code == 200
    assertTemplateUsed(response, "agenda/task-form-edit.html")


def test_edit_post(client, folder, task, user):
    data = {
        "folder": folder.id,
        "description": "Finish unit testing",
        "status": "Pending",
        "user": user.id,
    }
    response = client.post(reverse("agenda:edit", args=[task.id]), data)
    assert response.status_code == 302

    task_exists = Task.objects.filter(description="Finish unit testing").exists()
    assert task_exists
