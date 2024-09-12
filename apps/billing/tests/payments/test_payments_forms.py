import pytest

from apps.billing.payments.forms import PaymentForm

pytestmark = pytest.mark.django_db


def test_form_valid(payment_data):
    form = PaymentForm(payment_data)

    assert form.is_valid()
