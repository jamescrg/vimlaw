import pytest

from apps.billing.invoices.forms import InvoiceForm

pytestmark = pytest.mark.django_db


def test_form_valid(invoice_data):
    form = InvoiceForm(invoice_data)

    assert form.is_valid()
