"""Semantic date presets: a stored "Today" always means today.

The date dropdown's presets used to stamp literal dates into the session;
sessions outlive the day they were stamped (file-backed on dev, 8-week
cookie age), so "Today" silently became "on or before <some past date>"
while the dropdown stayed lit. refresh_date_preset re-derives the date
window from filter_label on every read; custom ranges stay literal.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.tasks.models import Task
from apps.tasks.services import quick_date_filters, refresh_date_preset

pytestmark = pytest.mark.django_db


def stale_today_filter(user, days_old=1):
    """A session tasks_filter as the Today preset stamped days_old days ago."""
    stamped = timezone.localdate() - timedelta(days=days_old)
    return {
        "filter_label": "today",
        "status": ["Pending", "In progress", "On hold"],
        "date_due_max": stamped.strftime("%Y-%m-%d"),
        "date_due_min": "",
        "has_due_date": "",
        "matter": None,
        "user": user.id,
        "order_by": "date_due",
    }


def test_refresh_date_preset_restamps_presets():
    today = timezone.localdate()
    fresh = quick_date_filters(today)
    for label in ("today", "next_workday", "next7", "week", "next_week"):
        stale = {"filter_label": label, "date_due_min": "x", "date_due_max": "y"}
        refreshed = refresh_date_preset(stale, today)
        assert refreshed["date_due_min"] == fresh[label]["date_due_min"]
        assert refreshed["date_due_max"] == fresh[label]["date_due_max"]


def test_refresh_date_preset_leaves_custom_and_unknown_alone():
    today = timezone.localdate()
    for label in ("custom", None, "bogus"):
        data = {"filter_label": label, "date_due_min": "2026-01-01"}
        assert refresh_date_preset(data, today) == data


def test_stale_today_preset_shows_todays_tasks(client, user):
    """The original bug: a Today filter stamped yesterday hid tasks due today."""
    due_today = Task.objects.create(
        user=user,
        description="Due today",
        status="Pending",
        date_due=timezone.localdate(),
        importance=4,
    )

    session = client.session
    session["tasks_filter"] = stale_today_filter(user)
    session.save()

    response = client.get(reverse("tasks:list"))
    assert response.status_code == 200
    assert response.context["filter_label"] == "today"
    assert due_today in list(response.context["objects"])

    # The refreshed window is persisted so the modal reads the same state.
    stored = client.session["tasks_filter"]
    assert stored["date_due_max"] == timezone.localdate().strftime("%Y-%m-%d")


def test_custom_range_stays_literal(client, user):
    """An explicit range must never move with the calendar."""
    yesterday = timezone.localdate() - timedelta(days=1)
    due_today = Task.objects.create(
        user=user,
        description="Due today",
        status="Pending",
        date_due=timezone.localdate(),
        importance=4,
    )

    session = client.session
    filter_data = stale_today_filter(user)
    filter_data["filter_label"] = "custom"
    session["tasks_filter"] = filter_data
    session.save()

    response = client.get(reverse("tasks:list"))
    assert due_today not in list(response.context["objects"])
    stored = client.session["tasks_filter"]
    assert stored["date_due_max"] == yesterday.strftime("%Y-%m-%d")


def test_filter_modal_shows_refreshed_dates(client, user):
    """The modal's date inputs render the current preset window, not the
    stamped-at date."""
    session = client.session
    session["tasks_filter"] = stale_today_filter(user)
    session.save()

    response = client.get(reverse("tasks:filter"))
    assert response.status_code == 200
    form = response.context["filter"].form
    assert form.data["date_due_max"] == timezone.localdate().strftime("%Y-%m-%d")


def test_matter_tab_refreshes_presets(client, user, matter):
    """The matter Tasks tab shares the presets and must refresh them too."""
    due_today = Task.objects.create(
        user=user,
        matter=matter,
        description="Due today",
        status="Pending",
        date_due=timezone.localdate(),
        importance=4,
    )

    session = client.session
    filter_data = stale_today_filter(user)
    filter_data["matter"] = matter.id
    session["matter_tasks_filter"] = filter_data
    session.save()

    response = client.get(reverse("matters:tasks-list", args=[matter.id]))
    assert response.status_code == 200
    assert due_today in list(response.context["objects"])
