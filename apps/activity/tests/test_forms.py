import pytest

from apps.activity.time.forms import TimeEntryForm

pytestmark = pytest.mark.django_db


def test_form_valid(entry_data):
    data = entry_data
    form = TimeEntryForm(data)
    assert form.is_valid()
