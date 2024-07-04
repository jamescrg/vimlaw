import pytest

from apps.agenda.forms import TaskForm

pytestmark = pytest.mark.django_db


def test_form_valid(task_data):
    data = task_data
    form = TaskForm(data)
    assert form.is_valid()
