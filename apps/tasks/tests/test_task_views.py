import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


def test_index(client, folder, task, matter):
    response = client.get("/tasks")
    assert response.status_code == 302
    response = client.get(reverse("tasks:index"))
    assert response.status_code == 200
    assertTemplateUsed(response, "tasks/list.html")
    assert response.context["app"] == "tasks"


def test_add_post(client, folder, task_data):
    task_data["description"] = "New title"
    task_data["date_due"] = ""
    task_data["matter_id"] = ""
    task_data["importance"] = "1"
    response = client.post("/tasks/add", task_data)
    assert response.status_code == 204
    found = Task.objects.filter(description=task_data["description"]).first()
    assert found


def test_edit_get(client, task):
    response = client.get(f"/tasks/{task.id}/edit")
    assert response.status_code == 200
    assertTemplateUsed(response, "tasks/form.html")


def test_edit_post(client, folder, task, user):
    data = {
        "folder": folder.id,
        "description": "Finish unit testing",
        "status": "Pending",
        "user": user.id,
        "importance": 1,
    }
    response = client.post(reverse("tasks:edit", args=[task.id]), data)
    assert response.status_code == 204  # HTMX response on success


# -----------------------------------------------------
# matters panel (opt-in tasks layout)
# -----------------------------------------------------
def test_filter_matter_admin(client, user, folder, task):
    admin_task = Task.objects.create(
        user=user,
        folder=folder,
        description="Renew CLE credits",
        date_due="2024-12-07",
        status="Pending",
    )
    response = client.post(reverse("tasks:filter-matter-admin"))
    assert response.status_code == 200
    ids = [t.id for t in response.context["objects"]]
    assert admin_task.id in ids
    assert task.id not in ids


def test_filter_matter_all_clears_admin(client, user, folder, task):
    admin_task = Task.objects.create(
        user=user,
        folder=folder,
        description="Renew CLE credits",
        date_due="2024-12-07",
        status="Pending",
    )
    client.post(reverse("tasks:filter-matter-admin"))
    response = client.post(reverse("tasks:filter-matter", args=[0]))
    assert response.status_code == 200
    ids = [t.id for t in response.context["objects"]]
    assert admin_task.id in ids
    assert task.id in ids


def test_filter_matter_clears_admin(client, task, matter):
    client.post(reverse("tasks:filter-matter-admin"))
    response = client.post(reverse("tasks:filter-matter", args=[matter.id]))
    assert response.status_code == 200
    ids = [t.id for t in response.context["objects"]]
    assert task.id in ids


def test_filter_modal_matter_clears_admin(client, task, matter):
    client.post(reverse("tasks:filter-matter-admin"))
    response = client.post(reverse("tasks:filter"), {"matter": matter.id})
    assert response.status_code == 204
    session_filter = client.session["tasks_filter"]
    assert session_filter["no_matter"] == ""


def test_list_classic_layout(client, task):
    response = client.get(reverse("tasks:index"))
    assert response.context["panel_layout"] is False
    assert b"tasks-matters-panel" not in response.content


def test_list_panel_layout(client, user, task, matter):
    user.tasks_layout = "panel"
    user.save(update_fields=["tasks_layout"])
    response = client.get(reverse("tasks:index"))
    assert response.context["panel_layout"] is True
    assert b"tasks-matters-panel" in response.content
    assert b"task-matter-sep" in response.content


# -----------------------------------------------------
# edge case tests - nonexistent records
# -----------------------------------------------------
def test_edit_nonexistent(client):
    response = client.get("/tasks/99999/edit")
    assert response.status_code == 404
