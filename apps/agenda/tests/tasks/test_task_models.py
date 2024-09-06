import pytest

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
