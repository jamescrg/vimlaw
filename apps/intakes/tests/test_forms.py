import pytest


from apps.intakes.forms import IntakeForm
from apps.intakes.forms import NoteForm


pytestmark = pytest.mark.django_db


def test_intake_form_valid(intake_data):
    data = intake_data
    form = IntakeForm(data)
    assert form.is_valid()


def test_intake_name(intake_data):
    data = intake_data
    data["name"] = "a"
    form = IntakeForm(data)
    assert not form.is_valid()
    assert "must be greater" in form.errors["name"][0]

    data = intake_data
    data["name"] = "s" * 55
    form = IntakeForm(intake_data)
    assert not form.is_valid()
    assert "must be fewer" in form.errors["name"][0]


def test_intake_address(intake_data):
    data = intake_data
    data["address"] = "s" * 255
    form = IntakeForm(intake_data)
    assert not form.is_valid()
    assert "must be fewer" in form.errors["address"][0]


def test_intake_phone_and_email(intake_data):
    data = intake_data
    data["phone"] = "0" * 21
    form = IntakeForm(intake_data)
    assert not form.is_valid()
    assert "must be fewer" in form.errors["phone"][0]

    data = intake_data
    data["email"] = "s" * 10
    form = IntakeForm(intake_data)
    assert not form.is_valid()
    assert "Invalid email" in form.errors["email"][0]


def test_note_form_valid(note_data):
    data = note_data
    form = NoteForm(data)
    assert form.is_valid()
