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


def test_any_user_can_assign_teammate(staff_user, admin_user):
    _apply_task_blocks(
        block([{"description": "Call the client", "user": "James Craig"}]),
        staff_user,
    )
    assert Task.objects.get().user_id == admin_user.id


def test_admin_can_assign_teammate(admin_user, staff_user):
    _apply_task_blocks(
        block([{"description": "Call the client", "user": "Pat Lee"}]),
        admin_user,
    )
    assert Task.objects.get().user_id == staff_user.id


def test_unresolved_assignee_defaults_to_requester(staff_user, admin_user):
    _apply_task_blocks(
        block([{"description": "Call the client", "user": "Nobody Real"}]),
        staff_user,
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


# ── Overnight plans ──────────────────────────────────────────────────────────


@pytest.fixture
def mock_gemini_sync(monkeypatch):
    def _set(response="1. Close out the Smith matter."):
        calls = {}

        def fake(system_context, messages, **kwargs):
            calls["system_context"] = system_context
            return (response, 200, 80)

        monkeypatch.setattr("apps.case.ai.gemini_client.send_to_gemini", fake)
        return calls

    return _set


def _seed_auto_threads(matter):
    from apps.case.ai.auto_summary import AUTO_AGENDA_TITLE, AUTO_SUMMARY_TITLE
    from apps.case.ai.models import Message

    for title, text in [
        (AUTO_SUMMARY_TITLE, "Boundary line disputed at the north fence."),
        (AUTO_AGENDA_TITLE, "Depose the surveyor, then move for summary judgment."),
    ]:
        conv = Conversation.objects.create(matter=matter, title=title, user=None)
        Message.objects.create(conversation=conv, role="user", content="prompt")
        Message.objects.create(conversation=conv, role="assistant", content=text)


def test_overnight_plan_creates_ready_conversation(
    admin_user, matter, mock_gemini_sync
):
    from apps.dash.agenda import generate_overnight_plan

    _seed_auto_threads(matter)
    calls = mock_gemini_sync()
    generate_overnight_plan(admin_user.id)

    conversation = Conversation.objects.get(agenda_user=admin_user)
    messages = list(conversation.messages.all())
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].content == AUTO_START_MESSAGE
    assert messages[1].content == "1. Close out the Smith matter."
    # Thorough context carries both nightly threads
    assert "Boundary line disputed" in calls["system_context"]
    assert "Depose the surveyor" in calls["system_context"]


def test_overnight_plan_replaces_previous(admin_user, matter, mock_gemini_sync):
    from apps.dash.agenda import generate_overnight_plan

    mock_gemini_sync()
    generate_overnight_plan(admin_user.id)
    old_id = Conversation.objects.get(agenda_user=admin_user).id

    mock_gemini_sync("2. New day, new plan.")
    generate_overnight_plan(admin_user.id)

    conversation = Conversation.objects.get(agenda_user=admin_user)
    assert conversation.id != old_id
    assert conversation.messages.count() == 2
    assert conversation.messages.last().content == "2. New day, new plan."


def test_overnight_plan_failure_keeps_previous(
    admin_user, matter, mock_gemini_sync, monkeypatch
):
    from apps.dash.agenda import generate_overnight_plan

    mock_gemini_sync()
    generate_overnight_plan(admin_user.id)

    def boom(*args, **kwargs):
        raise Exception("Gemini down")

    monkeypatch.setattr("apps.case.ai.gemini_client.send_to_gemini", boom)
    generate_overnight_plan(admin_user.id)

    conversation = Conversation.objects.get(agenda_user=admin_user)
    assert conversation.messages.last().content == "1. Close out the Smith matter."


def test_window_shows_overnight_plan_without_generating(
    admin_client, admin_user, matter, mock_gemini_sync, monkeypatch
):
    from apps.dash.agenda import generate_overnight_plan

    mock_gemini_sync()
    generate_overnight_plan(admin_user.id)

    def fail(*args, **kwargs):
        raise AssertionError("window should not trigger generation")

    monkeypatch.setattr("apps.dash.agenda._start_processing", fail)
    response = admin_client.get("/dash/agenda/")
    assert response.status_code == 200
    assert b"Close out the Smith matter" in response.content


def test_overnight_plan_folds_in_discussion(admin_user, matter, mock_gemini_sync):
    from apps.case.ai.models import Message
    from apps.dash.agenda import generate_overnight_plan

    mock_gemini_sync()
    generate_overnight_plan(admin_user.id)
    conversation = Conversation.objects.get(agenda_user=admin_user)
    Message.objects.create(
        conversation=conversation,
        role="user",
        content="Never schedule me for depositions on Fridays.",
        user=admin_user,
    )
    Message.objects.create(
        conversation=conversation,
        role="assistant",
        content="Noted, Fridays stay deposition-free.",
    )

    calls = mock_gemini_sync("2. Fresh plan, Fridays clear.")
    generate_overnight_plan(admin_user.id)

    assert "Never schedule me for depositions on Fridays" in calls["system_context"]
    assert "1. Close out the Smith matter." in calls["system_context"]
    fresh = Conversation.objects.get(agenda_user=admin_user)
    assert fresh.messages.count() == 2
    assert fresh.messages.last().content == "2. Fresh plan, Fridays clear."


def test_overnight_plan_without_discussion_has_no_feedback(
    admin_user, matter, mock_gemini_sync
):
    from apps.dash.agenda import generate_overnight_plan

    mock_gemini_sync()
    generate_overnight_plan(admin_user.id)

    calls = mock_gemini_sync("2. Another fresh plan.")
    generate_overnight_plan(admin_user.id)

    assert "FEEDBACK" not in calls["system_context"]


def test_refresh_daily_plans_queues_active_users(admin_user, staff_user):
    from unittest.mock import patch

    from apps.dash.agenda import refresh_daily_plans

    staff_user.is_active = False
    staff_user.save()

    with patch("django_q.tasks.async_task") as async_task:
        count = refresh_daily_plans()

    assert count == 1
    async_task.assert_called_once_with(
        "apps.dash.agenda.generate_overnight_plan",
        admin_user.id,
        task_name=f"DailyPlan-{admin_user.id}",
        group="daily_plan",
    )


def test_scheduled_plans_guarded_off_prod(admin_user, settings):
    from unittest.mock import patch

    from apps.dash.agenda import scheduled_refresh_daily_plans

    settings.ENV = "dev"
    with patch("django_q.tasks.async_task") as async_task:
        assert scheduled_refresh_daily_plans() == 0
    async_task.assert_not_called()
