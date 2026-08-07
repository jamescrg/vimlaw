"""Semantic date presets + user chips on the Activity time tab.

Same mechanism as the tasks tab (see apps/tasks/tests/test_date_presets.py):
filter_label is the source of truth and the stored window is re-derived
from today on every read, so a session's "Today" / "This Week" never goes
stale. The chips share the tasks pinned set (CustomUser.task_user_chips).
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.activity.presets import activity_date_filters, detect_filter_label
from apps.activity.time.models import TimeEntry

pytestmark = pytest.mark.django_db


def stale_filter(user, label, days_old=7):
    stamped = timezone.localdate() - timedelta(days=days_old)
    return {
        "filter_label": label,
        "date_min": stamped.strftime("%Y-%m-%d"),
        "date_max": stamped.strftime("%Y-%m-%d"),
        "matter": None,
        "keyword": "",
        "comp": None,
        "order_by": "-date",
        "user": user.id,
    }


def test_detect_filter_label_round_trips_presets():
    today = timezone.localdate()
    for label, preset in activity_date_filters(today).items():
        assert detect_filter_label(preset, today) == label


def test_stale_today_preset_shows_todays_entries(client, user, matter):
    entry = TimeEntry.objects.create(
        user_id=user.id,
        matter=matter,
        date=timezone.localdate(),
        hours=1,
        rate=300,
        comp=False,
        entered=False,
        actions="Draft letter",
    )

    session = client.session
    session["time_filter"] = stale_filter(user, "today")
    session.save()

    response = client.get(reverse("activity:time-list"))
    assert response.status_code == 200
    assert response.context["filter_label"] == "today"
    assert entry in list(response.context["objects"])

    # The refreshed window is persisted back to the session.
    stored = client.session["time_filter"]
    assert stored["date_max"] == timezone.localdate().strftime("%Y-%m-%d")


def test_custom_range_stays_literal(client, user, matter):
    entry = TimeEntry.objects.create(
        user_id=user.id,
        matter=matter,
        date=timezone.localdate(),
        hours=1,
        rate=300,
        comp=False,
        entered=False,
        actions="Draft letter",
    )

    session = client.session
    session["time_filter"] = stale_filter(user, "custom")
    session.save()

    response = client.get(reverse("activity:time-list"))
    assert entry not in list(response.context["objects"])


def test_chips_render_and_share_task_pins(client, user):
    user.task_user_chips = [user.id]
    user.save(update_fields=["task_user_chips"])

    response = client.get(reverse("activity:time-list"))
    assert b"user-chips" in response.content
    assert user.chip_initials.encode() in response.content


def test_toggle_chip_pins_and_unpins(client, user):
    url = reverse("activity:toggle-chip", args=[user.id])

    response = client.post(url)
    assert response.status_code == 204
    user.refresh_from_db()
    assert user.task_user_chips == [user.id]

    response = client.post(url)
    user.refresh_from_db()
    assert user.task_user_chips == []
