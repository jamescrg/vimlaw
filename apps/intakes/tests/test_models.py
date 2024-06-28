import pytest

pytestmark = pytest.mark.django_db


def test_intake_string(intake):
    assert str(intake) == f"{intake.name} : {intake.id}"


def test_intake_content(intake):
    expected_values = {
        "name": "Mohandas Gandhi",
        "address": "225 Paper Street, Porbandar, India",
        "phone": "123.456.7890",
        "email": "gandhi@gandhi.com",
    }
    for key, val in expected_values.items():
        assert getattr(intake, key) == val


def test_note_string(note):
    assert str(note) == f"{note.type} : {note.id}"


def test_note_content(note, user, intake):
    expected_values = {
        "user": user,
        "intake": intake,
        "date": "2022-12-28",
        "time": "00:00",
        "type": "General",
        "details": "",
    }
    for key, val in expected_values.items():
        assert getattr(note, key) == val
