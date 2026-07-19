"""Inbound Google sync must convert RFC3339 datetimes to the app's zone
before storing wall-clock values. Storing the UTC clock verbatim shifted
every synced event +4h per sync round trip (the 2026-07-17 miscalendared
hearing)."""

from datetime import date, time

import pytest

from apps.calendar.google import _parse_google_event

pytestmark = pytest.mark.django_db


def google_event(start, end):
    return {
        "summary": "Hearing via Zoom",
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }


def test_utc_datetimes_convert_to_eastern():
    # 14:30Z on July 17 is 10:30 AM EDT — the exact incident shape.
    data = _parse_google_event(
        google_event("2026-07-17T14:30:00Z", "2026-07-17T16:30:00Z")
    )
    assert data["date"] == date(2026, 7, 17)
    assert data["start_time"] == time(10, 30)
    assert data["end_time"] == time(12, 30)


def test_offset_datetimes_pass_through():
    data = _parse_google_event(
        google_event("2026-07-17T10:30:00-04:00", "2026-07-17T12:30:00-04:00")
    )
    assert data["date"] == date(2026, 7, 17)
    assert data["start_time"] == time(10, 30)
    assert data["end_time"] == time(12, 30)


def test_utc_date_rollover_lands_on_local_date():
    # 02:30Z July 18 is still 10:30 PM EDT on July 17.
    data = _parse_google_event(
        google_event("2026-07-18T02:30:00Z", "2026-07-18T03:30:00Z")
    )
    assert data["date"] == date(2026, 7, 17)
    assert data["start_time"] == time(22, 30)


def test_winter_offset_is_five_hours():
    # EST (January): 15:30Z is 10:30 AM.
    data = _parse_google_event(
        google_event("2026-01-15T15:30:00Z", "2026-01-15T16:30:00Z")
    )
    assert data["start_time"] == time(10, 30)


def test_all_day_events_unchanged():
    data = _parse_google_event(
        {
            "summary": "Deadline",
            "start": {"date": "2026-07-17"},
            "end": {"date": "2026-07-18"},
        }
    )
    assert data["date"] == date(2026, 7, 17)
    assert data["start_time"] is None
    assert data["end_time"] is None
