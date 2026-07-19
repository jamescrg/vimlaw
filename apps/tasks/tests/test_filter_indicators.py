"""Tests for the date-dropdown / Filter-button indicator coherence on Tasks (root).

Exercises the matrix: each cell sets up a known session state (via quick-filter
button, modal POST, or direct session write), then asserts that both
`custom_filter_active` and `filter_label` reflect the intended truth.
"""

from datetime import date, timedelta

import pytest
from django.urls import reverse

from apps.tasks.views import _detect_filter_label

pytestmark = pytest.mark.django_db


# ---------- Pure helper ----------


def test_detect_label_all_when_empty():
    assert _detect_filter_label({}, date(2026, 5, 15)) == "all"


def test_detect_label_unscheduled_when_has_due_date_false():
    assert (
        _detect_filter_label({"has_due_date": "false"}, date(2026, 5, 15))
        == "unscheduled"
    )


def test_detect_label_today():
    today = date(2026, 5, 15)
    assert _detect_filter_label({"date_due_max": str(today)}, today) == "today"


def test_detect_label_week():
    today = date(2026, 5, 15)
    end_of_week = today + timedelta(days=6 - today.weekday())
    assert _detect_filter_label({"date_due_max": str(end_of_week)}, today) == "week"


def test_detect_label_next_week():
    today = date(2026, 5, 15)  # a Friday
    next_monday = today + timedelta(days=7 - today.weekday())
    next_sunday = next_monday + timedelta(days=6)
    assert (
        _detect_filter_label(
            {"date_due_min": str(next_monday), "date_due_max": str(next_sunday)},
            today,
        )
        == "next_week"
    )


def test_detect_label_custom_with_date_due_min():
    today = date(2026, 5, 15)
    # Quick filters never set date_due_min, so any value here means custom.
    assert (
        _detect_filter_label(
            {"date_due_min": "2026-04-01", "date_due_max": "2026-04-15"}, today
        )
        == "custom"
    )


def test_detect_label_custom_when_date_due_max_not_a_preset():
    today = date(2026, 5, 15)
    assert _detect_filter_label({"date_due_max": "2026-04-01"}, today) == "custom"


def test_detect_label_custom_for_partial_range_with_only_min():
    today = date(2026, 5, 15)
    assert _detect_filter_label({"date_due_min": "2026-05-01"}, today) == "custom"


# ---------- Integration: session state through the actual views ----------


def _session_for(client, key):
    return client.session.get(key, {})


def test_default_state_filter_button_off(client):
    response = client.get(reverse("tasks:list"))
    assert response.status_code == 200
    assert response.context["custom_filter_active"] in (False, None, {})


def test_quick_filter_today_does_not_light_filter_button(client):
    client.post(reverse("tasks:filter-quick", args=["today"]))
    response = client.get(reverse("tasks:list"))
    assert response.context["filter_label"] == "today"
    assert response.context["custom_filter_active"] in (False, None, {})


def test_quick_filter_next_week_sets_forward_window(client):
    client.post(reverse("tasks:filter-quick", args=["next_week"]))
    session = _session_for(client, "tasks_filter")
    today = date.today()
    next_monday = today + timedelta(days=7 - today.weekday())
    next_sunday = next_monday + timedelta(days=6)
    assert session.get("filter_label") == "next_week"
    assert session.get("date_due_min") == str(next_monday)
    assert session.get("date_due_max") == str(next_sunday)

    response = client.get(reverse("tasks:list"))
    assert response.context["filter_label"] == "next_week"
    assert response.context["custom_filter_active"] in (False, None, {})


def test_quick_filter_does_not_clobber_modal_set_status(client):
    """Status="Complete" set via modal must survive a quick-filter click."""
    # User sets status=Complete via modal. status is multi-valued, so the
    # session stores it as a list.
    client.post(reverse("tasks:filter"), {"status": "Complete"})
    pre = _session_for(client, "tasks_filter")
    assert pre.get("status") == ["Complete"]

    # User then clicks "Today" — status should NOT be reset to Pending.
    client.post(reverse("tasks:filter-quick", args=["today"]))
    post = _session_for(client, "tasks_filter")
    assert post.get("status") == ["Complete"]
    assert post.get("filter_label") == "today"


def test_modal_with_status_complete_lights_filter_button(client):
    client.post(reverse("tasks:filter"), {"status": "Complete"})
    response = client.get(reverse("tasks:list"))
    assert response.context["custom_filter_active"]


def test_modal_with_custom_date_range_resolves_to_custom(client):
    response = client.post(
        reverse("tasks:filter"),
        {"date_due_min": "2026-04-01", "date_due_max": "2026-04-15"},
    )
    assert response.status_code == 204
    response = client.get(reverse("tasks:list"))
    assert response.context["filter_label"] == "custom"


def test_modal_with_today_date_resolves_to_today_preset(client):
    today = date.today()
    response = client.post(reverse("tasks:filter"), {"date_due_max": str(today)})
    assert response.status_code == 204
    response = client.get(reverse("tasks:list"))
    assert response.context["filter_label"] == "today"


def test_modal_apply_strips_csrf_token_from_session(client):
    client.post(reverse("tasks:filter"), {"matter": ""})
    session_filter = _session_for(client, "tasks_filter")
    assert "csrfmiddlewaretoken" not in session_filter


def test_modal_apply_preserves_other_session_state(client):
    # Set a date via quick filter first.
    client.post(reverse("tasks:filter-quick", args=["today"]))
    pre = _session_for(client, "tasks_filter")
    date_due_max = pre.get("date_due_max")
    assert date_due_max

    # Apply the modal with only status, leaving date_due_max out of POST.
    client.post(reverse("tasks:filter"), {"status": "Complete"})
    post = _session_for(client, "tasks_filter")
    # Merge preserves the prior date setting.
    assert post.get("date_due_max") == date_due_max
    assert post.get("status") == ["Complete"]


def test_modal_apply_keeps_preset_label_despite_unknown_has_due_date(client):
    """The modal's has_due_date select posts "unknown" for its empty state;
    that must not flip the date dropdown off the active preset."""
    today = date.today()
    client.post(reverse("tasks:filter-quick", args=["today"]))
    # Mirror what the rendered modal posts: status, the date, and the
    # NullBooleanSelect's "unknown" sentinel.
    client.post(
        reverse("tasks:filter"),
        {"status": "Pending", "date_due_max": str(today), "has_due_date": "unknown"},
    )
    post = _session_for(client, "tasks_filter")
    assert post.get("has_due_date") == ""
    assert post.get("filter_label") == "today"
