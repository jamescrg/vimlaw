import pytest

from apps.trust.forms import TransactionForm


pytestmark = pytest.mark.django_db


def test_form_valid(transaction_data):
    data = transaction_data
    form = TransactionForm(data)
    assert form.is_valid()
