import json
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.activity.time.models import TimeEntry
from apps.case.ai.models import Conversation
from apps.dash.agenda import (
    AUTO_START_MESSAGE,
    _agenda_context,
    _apply_task_blocks,
)
from apps.intakes.models import Intake
from apps.matters.models import Matter
from apps.tasks.models import Task

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _inline_threads(monkeypatch):
    import threading

    class InlineThread:
        def __init__(self, target=None, args=(), daemon=None):
            self._target = target
            self._args = args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(threading, "Thread", InlineThread)


@pytest.fixture
def mock_gemini(monkeypatch):
    def _set(response="1. Prepare for the Smith hearing."):
        monkeypatch.setattr(
            "apps.case.ai.gemini_client.send_to_gemini_streaming",
            lambda system, messages, **kwargs: (response, 100, 50),
        )

    return _set


@pytest.fixture
def admin_user():
    user = CustomUser.objects.create(
        username="james",
        first_name="James",
        last_name="Craig",
        email="admin@example.com",
        role="ADMIN",
    )
    user.set_password("pw")
    user.save()
    return user


@pytest.fixture
def staff_user():
    user = CustomUser.objects.create(
        username="paralegal",
        first_name="Pat",
        last_name="Lee",
        email="staff@example.com",
        role="USER",
    )
    user.set_password("pw")
    user.save()
    return user


@pytest.fixture
def admin_client(admin_user):
    client = Client()
    client.login(username="james", password="pw")
    client.get("/dash/")
    return client


@pytest.fixture
def matter(admin_user):
    return Matter.objects.create(
        name="Smith Boundary",
        status="Open",
        description="Boundary dispute",
        work_status="Awaiting survey",
        user=admin_user,
    )


def test_window_auto_starts(admin_client, admin_user, mock_gemini):
    mock_gemini()
    response = admin_client.get("/dash/agenda/")
    assert response.status_code == 200
    conversation = Conversation.objects.get()
    assert conversation.agenda_user_id == admin_user.id
    assert conversation.matter_id is None and conversation.intake_id is None
    assert conversation.vet_citations is False
    first = conversation.messages.get(role="user")
    assert first.content == AUTO_START_MESSAGE
    assert b"Suggested Agenda" in response.content


def test_reopen_resumes(admin_client, mock_gemini):
    mock_gemini()
    admin_client.get("/dash/agenda/")
    admin_client.get("/dash/agenda/")
    assert Conversation.objects.count() == 1


def test_send_appends(admin_client, mock_gemini):
    mock_gemini()
    admin_client.get("/dash/agenda/")
    response = admin_client.post(
        "/dash/agenda/send", {"message": "Expand to the week."}
    )
    assert response.status_code == 200
    conversation = Conversation.objects.get()
    assert conversation.messages.filter(role="user").count() == 2


def test_discard_then_fresh(admin_client, mock_gemini):
    mock_gemini()
    admin_client.get("/dash/agenda/")
    response = admin_client.post("/dash/agenda/discard")
    assert response.status_code == 200
    assert Conversation.objects.count() == 0
    admin_client.get("/dash/agenda/")
    assert Conversation.objects.count() == 1


def test_status_completes_agenda_conversation(admin_client, mock_gemini):
    mock_gemini()
    admin_client.get("/dash/agenda/")
    conversation = Conversation.objects.get()
    response = admin_client.get(f"/case/ai/status/{conversation.id}/")
    assert response.status_code == 200
    assistant = conversation.messages.get(role="assistant")
    assert "Smith hearing" in assistant.content
    conversation.refresh_from_db()
    assert not conversation.summary


# ── Task-block parsing ───────────────────────────────────────────────────────


def block(entries):
    return "Done.\n\n```create-tasks\n" + json.dumps(entries) + "\n```"


def test_task_block_creates_tasks(admin_user, matter):
    text = _apply_task_blocks(
        block(
            [
                {
                    "description": "Order the survey",
                    "matter": "smith boundary",
                    "due": "2026-08-01",
                    "importance": 9,
                }
            ]
        ),
        admin_user,
    )
    task = Task.objects.get()
    assert task.description == "Order the survey"
    assert task.matter_id == matter.id
    assert str(task.date_due) == "2026-08-01"
    assert task.importance == 7  # clamped
    assert task.status == "Pending"
    assert task.user_id == admin_user.id
    assert "Created task: **Order the survey**" in text
    assert "```create-tasks" not in text


def test_task_block_invalid_json_left_alone(admin_user):
    text = "```create-tasks\nnot json at all\n```"
    result = _apply_task_blocks(text, admin_user)
    assert result == text
    assert Task.objects.count() == 0


def test_non_admin_assignee_forced_to_self(staff_user, admin_user):
    _apply_task_blocks(
        block([{"description": "Call the client", "user": "James Craig"}]),
        staff_user,
    )
    assert Task.objects.get().user_id == staff_user.id


def test_admin_can_assign_teammate(admin_user, staff_user):
    _apply_task_blocks(
        block([{"description": "Call the client", "user": "Pat Lee"}]),
        admin_user,
    )
    assert Task.objects.get().user_id == staff_user.id


def test_short_description_skipped(admin_user):
    text = _apply_task_blocks(block([{"description": "ab"}]), admin_user)
    assert Task.objects.count() == 0
    assert "(no tasks created)" in text


# ── Context scoping ──────────────────────────────────────────────────────────


def test_context_scopes_by_role(admin_user, staff_user, matter):
    today = timezone.localdate()
    Task.objects.create(
        description="Admin's own task", status="Pending", user=admin_user
    )
    Task.objects.create(
        description="Staff member task", status="Pending", user=staff_user
    )
    TimeEntry.objects.create(
        date=today - timedelta(days=1),
        matter=matter,
        user=staff_user,
        actions="Drafted the demand letter",
        hours=2,
    )
    Intake.objects.create(name="Stale Caller", status="Open", date=today)

    admin_ctx = _agenda_context(admin_user)
    assert "Admin's own task" in admin_ctx
    assert "Staff member task" in admin_ctx
    assert "Drafted the demand letter" in admin_ctx
    assert "Stale Caller" in admin_ctx
    assert f"/case/{matter.id}/ai/conversations/new/" in admin_ctx

    staff_ctx = _agenda_context(staff_user)
    assert "Staff member task" in staff_ctx
    assert "Admin's own task" not in staff_ctx
    assert "Drafted the demand letter" in staff_ctx
