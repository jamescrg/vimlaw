from datetime import date

import pytest

from apps.agenda.tasks.models import Task

pytestmark = pytest.mark.django_db


def test_string(task):
    assert str(task) == f"{task.description} : {task.id}"


def test_content(task):
    expected_values = {
        "description": "Read about Mohandas Gandhi",
        "status": "Pending",
    }
    for key, val in expected_values.items():
        assert getattr(task, key) == val


def test_date_completed_set_on_status_complete(task):
    """date_completed should be auto-set when status changes to Complete"""
    assert task.date_completed is None
    task.status = "Complete"
    task.save()
    assert task.date_completed == date.today()


def test_date_completed_cleared_on_status_pending(task):
    """date_completed should be cleared when status changes from Complete to Pending"""
    task.status = "Complete"
    task.save()
    assert task.date_completed is not None

    task.status = "Pending"
    task.save()
    assert task.date_completed is None


def test_date_completed_cleared_on_status_in_progress(task):
    """date_completed should be cleared when status changes from Complete to In Progress"""
    task.status = "Complete"
    task.save()
    assert task.date_completed is not None

    task.status = "In Progress"
    task.save()
    assert task.date_completed is None


def test_date_completed_not_changed_when_already_complete(task):
    """date_completed should not change when saving an already Complete task"""
    task.status = "Complete"
    task.save()
    original_date = task.date_completed

    task.description = "Updated description"
    task.save()
    assert task.date_completed == original_date


def test_new_task_with_complete_status(user):
    """New task created with Complete status should have date_completed set"""
    task = Task.objects.create(
        user=user,
        description="New complete task",
        status="Complete",
        priority=1,
    )
    assert task.date_completed == date.today()
