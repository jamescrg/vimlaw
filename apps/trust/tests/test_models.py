import pytest

pytestmark = pytest.mark.django_db


def test_string(transaction):
    assert str(transaction) == f"{transaction.description} : {transaction.id}"


def test_content(transaction, contact):
    expectedValues = {
        "contact": contact,
        "date": "2022-12-29",
        "type": "Deposit",
        "description": "Retainer",
        "amount": 2000.00,
        "entered": 0,
        "confirmed": 0,
    }
    for key, val in expectedValues.items():
        assert getattr(transaction, key) == val
