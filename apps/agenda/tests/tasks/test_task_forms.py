import pytest

from apps.agenda.tasks.forms import TaskForm

pytestmark = pytest.mark.django_db


def test_form_valid(task_data):
    data = task_data
    form = TaskForm(data)
    assert form.is_valid()


# -----------------------------------------------------
# clean_description tests
# -----------------------------------------------------
def test_description_too_short(task_data):
    data = task_data.copy()
    data["description"] = "abc"  # 3 chars, min is 4
    form = TaskForm(data)
    assert not form.is_valid()
    assert "description" in form.errors
    assert "4 or more" in form.errors["description"][0]


def test_description_too_long(task_data):
    data = task_data.copy()
    data["description"] = "a" * 201  # 201 chars, max is 200
    form = TaskForm(data)
    assert not form.is_valid()
    assert "description" in form.errors
    assert "200 character" in form.errors["description"][0]


def test_description_valid_min_length(task_data):
    data = task_data.copy()
    data["description"] = "abcd"  # Exactly 4 chars
    form = TaskForm(data)
    assert form.is_valid()


def test_description_valid_max_length(task_data):
    data = task_data.copy()
    data["description"] = "a" * 200  # Exactly 200 chars
    form = TaskForm(data)
    assert form.is_valid()
