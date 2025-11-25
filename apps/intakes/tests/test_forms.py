import pytest

from apps.intakes.forms import IntakeForm, NoteForm

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
    # Test invalid phone number (not 10 digits)
    data = intake_data.copy()
    data["phone"] = "123"  # Too short
    form = IntakeForm(data)
    assert not form.is_valid()
    assert "10-digit" in form.errors["phone"][0]

    # Test valid phone number normalizes to digits
    data = intake_data.copy()
    data["phone"] = "(406) 363-1234"
    form = IntakeForm(data)
    assert form.is_valid()
    assert form.cleaned_data["phone"] == "4063631234"

    # Test invalid email
    data = intake_data.copy()
    data["email"] = "not-an-email"
    form = IntakeForm(data)
    assert not form.is_valid()
    assert "email" in form.errors["email"][0].lower()


def test_note_form_valid(note_data):
    data = note_data
    form = NoteForm(data)
    assert form.is_valid()
