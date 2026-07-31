from datetime import date, timedelta

import pytest

from apps.calendar.models import Event
from apps.dash.views import dash_events_context

pytestmark = pytest.mark.django_db


def _event(**kwargs):
    return Event.objects.create(description="Site visit", **kwargs)


def test_past_due_pending_events_stay_visible():
    today = date.today()
    past = _event(status="Pending", date=today - timedelta(days=1))
    upcoming = _event(status="Pending", date=today + timedelta(days=3))

    events = list(dash_events_context(None)["upcoming_events"])
    assert events == [past, upcoming]  # past-due sorts first


def test_resolved_and_undated_events_hidden():
    today = date.today()
    _event(status="Complete", date=today - timedelta(days=1))
    _event(status="Missed", date=today - timedelta(days=2))
    _event(status="Pending", date=None)

    assert list(dash_events_context(None)["upcoming_events"]) == []


def test_context_dates():
    today = date.today()
    context = dash_events_context(None)
    assert context["today"] == today
    assert context["tomorrow"] == today + timedelta(days=1)
    assert context["yesterday"] == today - timedelta(days=1)
