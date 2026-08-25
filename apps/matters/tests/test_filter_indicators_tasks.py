"""Tests for the filter-indicator coherence on the matter detail Tasks tab.

The toolbar mirrors the main tasks toolbar: a date quick-filter dropdown
(whose label reconciles against modal-set date bounds), one-click user
chips, and a Filter button that is the superset signal for modal-only
dimensions (status, importance, completion dates). The coverage focuses on:

- The Filter button lights up only when modal-only dimensions are non-default.
- Date bounds surface in the date dropdown ("Custom range"), not the Filter
  button; the user chips carry the user filter.
- The modal POST merges into existing session state and strips csrfmiddlewaretoken.
- The date quick-filter endpoint sets the label + window; chip pins toggle.
"""

import pytest
from django.urls import reverse
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _session_for(client, key):
    return client.session.get(key, {})


def test_default_state_filter_button_off(client, matter):
    response = client.get(reverse("matters:tasks-index", args=[matter.id]))
    assert response.status_code == 200
    assert response.context["custom_filter_active"] in (False, None, {})


def test_modal_with_status_complete_lights_filter_button(client, matter):
    client.post(
        reverse("matters:tasks-filter", args=[matter.id]),
        {"status": "Complete"},
    )
    response = client.get(reverse("matters:tasks-index", args=[matter.id]))
    assert response.context["custom_filter_active"]


def test_modal_with_date_due_shows_custom_label_not_filter_button(client, matter):
    client.post(
        reverse("matters:tasks-filter", args=[matter.id]),
        {"date_due_min": "2026-05-01"},
    )
    response = client.get(reverse("matters:tasks-index", args=[matter.id]))
    # The date dropdown owns the date dimension: it reads "Custom range"
    # (lit) while the Filter button stays off.
    assert response.context["filter_label"] == "custom"
    assert response.context["custom_filter_active"] in (False, None, {})


def test_importance_lights_filter_button(client, matter):
    # Importance no longer has a toolbar dropdown, so a lingering importance
    # filter must light the Filter button to stay visible.
    client.post(reverse("matters:tasks-filter-importance", args=[matter.id, 7]))
    response = client.get(reverse("matters:tasks-index", args=[matter.id]))
    assert response.context["custom_filter_active"]


def test_user_filter_does_not_light_filter_button(client, matter, user):
    client.post(reverse("matters:tasks-filter-user", args=[matter.id, user.id]))
    response = client.get(reverse("matters:tasks-index", args=[matter.id]))
    # The user chips carry the user filter's indicator.
    assert response.context["custom_filter_active"] in (False, None, {})
    assert response.context["user_id"] == user.id


def test_quick_filter_sets_label_and_window(client, matter):
    response = client.post(
        reverse("matters:tasks-filter-quick", args=[matter.id, "today"])
    )
    assert response.status_code == 204
    session_filter = _session_for(client, "matter_tasks_filter")
    assert session_filter["filter_label"] == "today"
    assert session_filter["date_due_max"] == str(timezone.localdate())
    assert session_filter["date_due_min"] == ""
    assert session_filter["matter"] == matter.id


def test_quick_filter_unknown_slug_404s(client, matter):
    response = client.post(
        reverse("matters:tasks-filter-quick", args=[matter.id, "bogus"])
    )
    assert response.status_code == 404


def test_toggle_chip_pins_and_unpins(client, matter, user):
    from apps.accounts.models import CustomUser

    other = CustomUser.objects.create_user(
        username="chipmate", email="chipmate@example.com", password="x"
    )
    response = client.post(
        reverse("matters:tasks-toggle-chip", args=[matter.id, other.id])
    )
    assert response.status_code == 204
    user.refresh_from_db()
    assert user.task_user_chips == [other.id]

    client.post(reverse("matters:tasks-toggle-chip", args=[matter.id, other.id]))
    user.refresh_from_db()
    assert user.task_user_chips == []


def test_modal_apply_strips_csrf_token_from_session(client, matter):
    client.post(
        reverse("matters:tasks-filter", args=[matter.id]),
        {"status": "Complete"},
    )
    session_filter = _session_for(client, "matter_tasks_filter")
    assert "csrfmiddlewaretoken" not in session_filter


def test_modal_apply_preserves_dropdown_state(client, matter):
    # Set an importance via its endpoint first.
    client.post(reverse("matters:tasks-filter-importance", args=[matter.id, 7]))
    pre = _session_for(client, "matter_tasks_filter")
    assert str(pre.get("importance")) == "7"

    # Apply the modal with only status, leaving importance out of POST.
    client.post(
        reverse("matters:tasks-filter", args=[matter.id]),
        {"status": "Complete"},
    )
    post = _session_for(client, "matter_tasks_filter")
    # Merge preserves the prior importance selection.
    assert str(post.get("importance")) == "7"
    # Status has been multi-valued since the multi-select status filter.
    assert post.get("status") == ["Complete"]
