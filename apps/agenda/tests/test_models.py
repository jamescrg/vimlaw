import pytest

pytestmark = pytest.mark.django_db


def test_string(task):
    assert str(task) == f"{task.title} : {task.id}"


def test_content(task):
    expected_values = {
        "title": "Read about Mohandas Gandhi",
        "status": "Pending",
    }
    for key, val in expected_values.items():
        assert getattr(task, key) == val
