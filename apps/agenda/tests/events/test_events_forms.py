import pytest

from apps.agenda.events.forms import EventForm

pytestmark = pytest.mark.django_db


def test_form_valid(matter, event_data):
    data = event_data
    data["matter"] = matter.id
    form = EventForm(data)
    assert form.is_valid()
