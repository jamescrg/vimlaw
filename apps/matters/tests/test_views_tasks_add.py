"""The matter tasks-add modal presets the current matter but keeps the full
open-matter list, so tasks can be filed on another matter without leaving
the page (also the path the command palette uses on matter pages)."""

import pytest
from django.urls import reverse

from apps.matters.models import Matter
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


@pytest.fixture
def other_matter(user, contact, practice_area):
    return Matter.objects.create(
        name="Other Matter",
        status="Open",
        practice_area=practice_area,
        client=contact,
        user=user,
    )


def test_add_modal_offers_all_open_matters(client, matter, other_matter):
    response = client.get(reverse("matters:tasks-add", kwargs={"id": matter.id}))
    assert response.status_code == 200
    content = response.content.decode()
    assert matter.name in content
    assert other_matter.name in content
    assert "readonly" not in content.split("</select>")[0]


def test_add_task_to_another_matter_without_redirect(
    client, user, matter, other_matter
):
    response = client.post(
        reverse("matters:tasks-add", kwargs={"id": matter.id}),
        {
            "description": "Cross-matter task",
            "user": user.id,
            "matter": other_matter.id,
            "importance": "4",
            "status": "Pending",
            "date_due": "",
        },
    )
    assert response.status_code == 204
    assert response.headers.get("HX-Trigger") == "tasksListChanged"
    task = Task.objects.get(description="Cross-matter task")
    assert task.matter == other_matter


def test_add_task_defaults_to_current_matter(client, user, matter):
    response = client.post(
        reverse("matters:tasks-add", kwargs={"id": matter.id}),
        {
            "description": "Local task",
            "user": user.id,
            "matter": "",
            "importance": "4",
            "status": "Pending",
            "date_due": "",
        },
    )
    assert response.status_code == 204
    assert Task.objects.get(description="Local task").matter == matter
