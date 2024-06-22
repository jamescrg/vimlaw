import pytest

pytestmark = pytest.mark.django_db


def test_string(event):
    assert str(event) == f"{event.description} : {event.id}"


def test_content(event):
    expectedValues = {
        "date": "2022-12-28",
        "party": "Client",
        "description": "File Answer",
        "status": "Pending",
    }
    for key, val in expectedValues.items():
        assert getattr(event, key) == val
