import pytest

from apps.contacts.forms import ContactForm

pytestmark = pytest.mark.django_db


def test_form_valid(contact_data):
    data = contact_data
    form = ContactForm(data)
    assert form.is_valid()


def test_name(contact_data):
    data = contact_data
    data["name"] = "a"
    form = ContactForm(data)
    assert not form.is_valid()
    assert "must be greater" in form.errors["name"][0]

    data = contact_data
    data["name"] = "s" * 55
    form = ContactForm(contact_data)
    assert not form.is_valid()
    assert "must be fewer" in form.errors["name"][0]


def test_company(contact_data):
    data = contact_data
    data["company"] = "s" * 55
    form = ContactForm(contact_data)
    assert not form.is_valid()
    assert "must be fewer" in form.errors["company"][0]


def test_address(contact_data):
    data = contact_data
    data["address"] = "s" * 255
    form = ContactForm(contact_data)
    assert not form.is_valid()
    assert "must be fewer" in form.errors["address"][0]


def test_phones_and_email(contact_data):
    # Test invalid phone numbers (not 10 digits)
    data = contact_data.copy()
    data["phone1"] = "123"  # Too short
    data["phone2"] = "456"
    data["phone3"] = "789"
    form = ContactForm(data)
    assert not form.is_valid()
    assert "10-digit" in form.errors["phone1"][0]
    assert "10-digit" in form.errors["phone2"][0]
    assert "10-digit" in form.errors["phone3"][0]

    # Test valid phone number normalizes to digits
    data = contact_data.copy()
    data["phone1"] = "(406) 363-1234"
    form = ContactForm(data)
    assert form.is_valid()
    assert form.cleaned_data["phone1"] == "4063631234"

    # Test invalid email
    data = contact_data.copy()
    data["email"] = "not-an-email"
    form = ContactForm(data)
    assert not form.is_valid()
    assert "email" in form.errors["email"][0].lower()


def test_notes(contact_data):
    data = contact_data
    data["notes"] = "s" * 255
    form = ContactForm(contact_data)
    assert not form.is_valid()
    assert "must be fewer" in form.errors["notes"][0]
