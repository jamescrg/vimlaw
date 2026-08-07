"""Tests for the date-dropdown / Filter-button indicator coherence.

Exercises the matrix from the plan: each cell sets up a known session state
(via quick-filter, modal POST, or direct session write), then asserts that
both `custom_filter_active` and `filter_label` reflect the intended truth.
"""

from datetime import date, timedelta

import pytest
from django.urls import reverse

from apps.activity.presets import detect_filter_label as _detect_filter_label

pytestmark = pytest.mark.django_db


# ---------- Pure helper ----------


def test_detect_label_all_when_empty():
    assert _detect_filter_label({}, date(2026, 5, 15)) == "all"


def test_detect_label_unbilled_when_entered_and_invoice_zero_without_dates():
    assert (
        _detect_filter_label({"entered": 0, "invoice": 0}, date(2026, 5, 15))
        == "unbilled"
    )


def test_detect_label_today():
    today = date(2026, 5, 15)
    assert (
        _detect_filter_label({"date_min": str(today), "date_max": str(today)}, today)
        == "today"
    )


def test_detect_label_yesterday():
    today = date(2026, 5, 15)
    y = today - timedelta(days=1)
    assert (
        _detect_filter_label({"date_min": str(y), "date_max": str(y)}, today)
        == "yesterday"
    )


def test_detect_label_this_week():
    today = date(2026, 5, 15)  # Friday
    monday = today - timedelta(days=today.weekday())
    assert (
        _detect_filter_label({"date_min": str(monday), "date_max": str(today)}, today)
        == "this_week"
    )


def test_detect_label_last_week():
    today = date(2026, 5, 15)
    monday = today - timedelta(days=today.weekday())
    last_monday = monday - timedelta(days=7)
    last_sunday = monday - timedelta(days=1)
    assert (
        _detect_filter_label(
            {"date_min": str(last_monday), "date_max": str(last_sunday)}, today
        )
        == "last_week"
    )


def test_detect_label_this_month():
    today = date(2026, 5, 15)
    month_start = today.replace(day=1)
    assert (
        _detect_filter_label(
            {"date_min": str(month_start), "date_max": str(today)}, today
        )
        == "this_month"
    )


def test_detect_label_last_month():
    today = date(2026, 5, 15)
    last_month_end = today.replace(day=1) - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    assert (
        _detect_filter_label(
            {
                "date_min": str(last_month_start),
                "date_max": str(last_month_end),
            },
            today,
        )
        == "last_month"
    )


def test_detect_label_custom_when_dates_dont_match_preset():
    today = date(2026, 5, 15)
    assert (
        _detect_filter_label(
            {"date_min": "2026-03-12", "date_max": "2026-04-03"}, today
        )
        == "custom"
    )


def test_detect_label_custom_when_partial_range():
    today = date(2026, 5, 15)
    assert (
        _detect_filter_label({"date_min": "2026-05-01", "date_max": ""}, today)
        == "custom"
    )


# ---------- Integration: session state through the actual views ----------


def _session_for(client, key):
    """Read a session value off the test client's persisted session."""
    return client.session.get(key, {})


def test_default_state_filter_button_off(client):
    response = client.get(reverse("activity:time-list"))
    assert response.status_code == 200
    assert response.context["custom_filter_active"] in (False, None, {})


def test_last_week_dropdown_does_not_light_filter_button(client):
    client.post(reverse("activity:time-filter-quick", args=["last_week"]))
    response = client.get(reverse("activity:time-list"))
    assert response.context["custom_filter_active"] in (False, None, {})
    assert response.context["filter_label"] == "last_week"


def test_unbilled_preset_does_not_light_filter_button(client):
    client.post(reverse("activity:time-filter-quick", args=["unbilled"]))
    response = client.get(reverse("activity:time-list"))
    assert response.context["custom_filter_active"] in (False, None, {})
    assert response.context["filter_label"] == "unbilled"


def test_modal_keyword_lights_filter_button(client):
    response = client.post(
        reverse("activity:time-filter"),
        {"actions": "deposition"},
    )
    assert response.status_code == 204
    response = client.get(reverse("activity:time-list"))
    assert response.context["custom_filter_active"]
    # No dates posted; label should resolve to "all".
    assert response.context["filter_label"] == "all"


def test_modal_with_preset_dates_resolves_to_preset_label(client):
    today = date.today()
    response = client.post(
        reverse("activity:time-filter"),
        {"date_min": str(today), "date_max": str(today)},
    )
    assert response.status_code == 204
    response = client.get(reverse("activity:time-list"))
    assert response.context["filter_label"] == "today"
    # Date dimension is visible in the dropdown, so the modal-only indicator
    # should NOT light up.
    assert response.context["custom_filter_active"] in (False, None, {})


def test_modal_with_custom_dates_resolves_to_custom(client):
    response = client.post(
        reverse("activity:time-filter"),
        {"date_min": "2026-03-12", "date_max": "2026-04-03"},
    )
    assert response.status_code == 204
    response = client.get(reverse("activity:time-list"))
    assert response.context["filter_label"] == "custom"


def test_modal_apply_strips_csrf_token_from_session(client):
    response = client.post(
        reverse("activity:time-filter"),
        {"actions": "research"},
    )
    assert response.status_code == 204
    session_filter = _session_for(client, "time_filter")
    assert "csrfmiddlewaretoken" not in session_filter


def test_modal_apply_preserves_quick_filter_state(client):
    # Set a quick-filter first.
    client.post(reverse("activity:time-filter-quick", args=["last_week"]))
    pre = _session_for(client, "time_filter")
    last_week_min = pre.get("date_min")
    last_week_max = pre.get("date_max")
    assert last_week_min and last_week_max

    # Apply the modal with just a keyword (no date fields posted).
    client.post(reverse("activity:time-filter"), {"actions": "discovery"})
    post = _session_for(client, "time_filter")
    # The merge preserves date_min/date_max from the prior quick-filter selection.
    assert post.get("date_min") == last_week_min
    assert post.get("date_max") == last_week_max
    # And the new keyword is in there too.
    assert post.get("actions") == "discovery"


def test_modal_entered_only_lights_filter_button_when_not_unbilled(client):
    response = client.post(
        reverse("activity:time-filter"),
        {"entered": "1"},
    )
    assert response.status_code == 204
    response = client.get(reverse("activity:time-list"))
    # filter_label resolved to "all" (no dates, entered=1 not the unbilled
    # pair), so entered triggers the modal-only indicator.
    assert response.context["filter_label"] == "all"
    assert response.context["custom_filter_active"]
