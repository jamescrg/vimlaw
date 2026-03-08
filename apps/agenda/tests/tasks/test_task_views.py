import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.agenda.tasks.models import Task

pytestmark = pytest.mark.django_db


def test_index(client, folder, task, matter):
    response = client.get("/agenda/tasks")
    assert response.status_code == 302
    response = client.get(reverse("agenda:tasks-index"))
    assert response.status_code == 200
    assertTemplateUsed(response, "agenda/tasks/list.html")
    assert response.context["app"] == "tasks"


def test_add_post(client, folder, task_data):
    task_data["description"] = "New title"
    task_data["date_due"] = ""
    task_data["matter_id"] = ""
    task_data["priority"] = "1"
    response = client.post("/agenda/tasks/add", task_data)
    assert response.status_code == 204
    found = Task.objects.filter(description=task_data["description"]).first()
    assert found


def test_edit_get(client, task):
    response = client.get(f"/agenda/tasks/{task.id}/edit")
    assert response.status_code == 200
    assertTemplateUsed(response, "agenda/tasks/form.html")


def test_edit_post(client, folder, task, user):
    data = {
        "folder": folder.id,
        "description": "Finish unit testing",
        "status": "Pending",
        "user": user.id,
        "priority": 1,
    }
    response = client.post(reverse("agenda:tasks-edit", args=[task.id]), data)
    assert response.status_code == 204  # HTMX response on success


# -----------------------------------------------------
# edge case tests - nonexistent records
# -----------------------------------------------------
def test_edit_nonexistent(client):
    response = client.get("/agenda/tasks/99999/edit")
    assert response.status_code == 404
