import re

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
# user filter chips
# -----------------------------------------------------
def test_user_chips_render_small_firm(client, user, task):
    """<= cap active users: everyone is a chip, no legacy dropdown."""
    response = client.get(reverse("tasks:index"))
    assert b"user-chips" in response.content
    # Whitespace-tolerant: djLint formats the shared chip component with the
    # monogram on its own line.
    assert re.search(rb">\s*OL\s*</button>", response.content)
    assert b"tasks-user-filter" not in response.content


def test_toggle_chip_pins_and_unpins(client, user):
    from apps.accounts.models import CustomUser

    other = CustomUser.objects.create(username="zed", email="z@example.com")
    response = client.post(reverse("tasks:toggle-chip", args=[other.id]))
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.task_user_chips == [other.id]

    client.post(reverse("tasks:toggle-chip", args=[other.id]))
    user.refresh_from_db()
    assert user.task_user_chips == []


def test_toggle_chip_cap(client, user):
    from apps.accounts.models import CustomUser

    extras = [
        CustomUser.objects.create(username=f"extra{i}", email=f"e{i}@example.com")
        for i in range(6)
    ]
    for extra in extras[:5]:
        client.post(reverse("tasks:toggle-chip", args=[extra.id]))
    client.post(reverse("tasks:toggle-chip", args=[extras[5].id]))
    user.refresh_from_db()
    assert len(user.task_user_chips) == 5
    assert extras[5].id not in user.task_user_chips


def test_filtered_unchipped_user_surfaces_as_chip(client, user, task):
    """Large firm, nothing pinned: filtering to a user still lights a chip."""
    from apps.accounts.models import CustomUser

    extras = [
        CustomUser.objects.create(username=f"extra{i}", email=f"e{i}@example.com")
        for i in range(6)
    ]
    target = extras[0]
    response = client.post(reverse("tasks:filter-user", args=[target.id]))
    assert re.search(rb">\s*EX\s*</button>", response.content)


# -----------------------------------------------------
# edge case tests - nonexistent records
# -----------------------------------------------------
def test_edit_nonexistent(client):
    response = client.get("/tasks/99999/edit")
    assert response.status_code == 404
