import pytest

pytestmark = pytest.mark.django_db


def test_string(entry):
    assert str(entry) == f"{entry.actions}"


def test_content(entry):
    expectedValues = {
        "date": "2020-01-07",
        "actions": "Call with client",
        "hours": 0.2,
    }
    for key, val in expectedValues.items():
        assert getattr(entry, key) == val
