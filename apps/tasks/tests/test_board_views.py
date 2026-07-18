import json

import pytest

from apps.accounts.models import CustomUser
from apps.checklists.models import Checklist, ChecklistItem


@pytest.mark.django_db
def test_board_view_renders(client, task):
    # Switch to board mode
    resp = client.post("/tasks/view-mode/board/")
    assert resp.status_code == 204
    assert resp.headers.get("HX-Trigger") == "tasksListChanged"

    # Index now renders the board with the task's column
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'id="tasks-board"' in body
    assert 'data-status-slug="pending"' in body
    assert f'data-task-id="{task.id}"' in body
    # All four columns present, in board order: the forward flow stays
    # contiguous and On hold is parked on the right.
    order = ["pending", "in-progress", "complete", "on-hold"]
    positions = [body.index(f'data-status-slug="{slug}"') for slug in order]
    assert positions == sorted(positions)


@pytest.mark.django_db
def test_board_card_selection(client, task):
    client.post("/tasks/view-mode/board/")

    # Unselected: select button present, card not marked selected.
    body = client.get("/").content.decode()
    assert f"/tasks/toggle-select/{task.id}/" in body
    assert "importance-4 selected" not in body

    # Toggle selection -> card carries the selected class + checked icon.
    assert client.post(f"/tasks/toggle-select/{task.id}/").status_code == 204
    body = client.get("/").content.decode()
    assert "importance-4 selected" in body
    assert "icon-square-check" in body


@pytest.mark.django_db
def test_board_move_changes_status_and_order(client, task):
    client.post("/tasks/view-mode/board/")
    resp = client.post(
        "/tasks/board/move/",
        data=json.dumps(
            {"task_id": task.id, "status_slug": "in-progress", "ordered_ids": [task.id]}
        ),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    task.refresh_from_db()
    assert task.status == "In progress"
    assert task.custom_order == 0


@pytest.mark.django_db
def test_board_move_to_complete_sets_completed_date(client, task):
    client.post("/tasks/view-mode/board/")
    client.post(
        "/tasks/board/move/",
        data=json.dumps(
            {"task_id": task.id, "status_slug": "complete", "ordered_ids": [task.id]}
        ),
        content_type="application/json",
    )
    task.refresh_from_db()
    assert task.status == "Complete"
    assert task.date_completed is not None


@pytest.mark.django_db
def test_view_mode_rejects_unknown(client):
    resp = client.post("/tasks/view-mode/bogus/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_cycle_user_skips_all_users(client, user):
    second = CustomUser.objects.create(
        username="Zara", email="zara@example.com", user_rate=100
    )
    # The [ / ] keyboard cycle: Ollie (the `user` fixture) <-> Zara,
    # wrapping, with NO All Users stop; from All Users the cycle is
    # entered at the first/last user.
    resp = client.post("/tasks/cycle-user/next/")
    assert resp.status_code == 204
    assert resp.headers.get("HX-Trigger") == "tasksListChanged"
    assert client.session["tasks_filter"]["user"] == user.id  # All -> first user

    client.post("/tasks/cycle-user/next/")
    assert client.session["tasks_filter"]["user"] == second.id  # -> next user

    client.post("/tasks/cycle-user/next/")
    assert client.session["tasks_filter"]["user"] == user.id  # wraps, skipping All

    client.post("/tasks/cycle-user/prev/")
    assert client.session["tasks_filter"]["user"] == second.id  # wraps back


@pytest.mark.django_db
def test_toolbar_has_user_filter(client, user):
    client.post("/tasks/view-mode/board/")
    body = client.get("/").content.decode()
    # Single user dropdown: All Users plus an entry per user.
    assert 'id="tasks-user-filter"' in body
    assert "/tasks/filter/user/0/" in body
    assert f"/tasks/filter/user/{user.id}/" in body


@pytest.mark.django_db
def test_quick_filter_keeps_board_view(client, task):
    client.post("/tasks/view-mode/board/")
    resp = client.post("/tasks/filter/quick/all")
    assert resp.status_code == 200
    assert 'id="tasks-board"' in resp.content.decode()


@pytest.mark.django_db
def test_board_move_to_complete_blocked_by_open_checklist(client, task):
    checklist = Checklist.objects.create(task=task)
    ChecklistItem.objects.create(
        checklist=checklist, description="Unfinished step", item_type="item"
    )
    client.post("/tasks/view-mode/board/")

    resp = client.post(
        "/tasks/board/move/",
        data=json.dumps(
            {"task_id": task.id, "status_slug": "complete", "ordered_ids": [task.id]}
        ),
        content_type="application/json",
    )

    # Move is rejected with a reason for the toast, and status is unchanged.
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "checklist" in body["message"].lower()
    task.refresh_from_db()
    assert task.status == "Pending"
    assert task.date_completed is None
