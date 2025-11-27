from datetime import date

import pytest

from apps.agenda.tasks.models import Task, TaskNote

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


def test_task_note_creation(task, user):
    """TaskNote can be created and associated with a task"""
    note = TaskNote.objects.create(
        task=task,
        user=user,
        date=date.today(),
        details="Test note content",
    )
    assert note.task == task
    assert note.user == user
    assert note.details == "Test note content"
    assert task.notes.count() == 1


def test_task_note_string(task, user):
    """TaskNote string representation"""
    note = TaskNote.objects.create(
        task=task,
        user=user,
        date=date.today(),
        details="Test note",
    )
    assert str(note) == f"Note for {task.description} on {date.today()}"


def test_task_notes_cascade_delete(task, user):
    """TaskNotes should be deleted when task is deleted"""
    TaskNote.objects.create(task=task, user=user, date=date.today(), details="Note 1")
    TaskNote.objects.create(task=task, user=user, date=date.today(), details="Note 2")
    assert TaskNote.objects.count() == 2

    task.delete()
    assert TaskNote.objects.count() == 0
