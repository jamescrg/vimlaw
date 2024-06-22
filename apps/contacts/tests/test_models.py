import pytest

pytestmark = pytest.mark.django_db


def test_string(contact):
    assert str(contact) == f"{contact.name} : {contact.id}"


def test_content(contact):
    expectedValues = {
        "name": "Mohandas Gandhi",
        "company": "Gandhi, PC",
        "phone1": "406.363.1234",
    }
    for key, val in expectedValues.items():
        assert getattr(contact, key) == val
