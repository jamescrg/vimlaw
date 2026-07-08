"""Tests for the Filter-button indicator coherence on the matter detail Tasks tab.

The matter tasks tab has no date quick-filter dropdown, so there's no
filter_label reconciliation to test. The coverage focuses on:

- The Filter button lights up only when modal-only dimensions are non-default.
- The importance / user dropdowns don't light the Filter button (they have
  their own indicators).
- The modal POST merges into existing session state and strips csrfmiddlewaretoken.
"""

import pytest
from django.urls import reverse

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


def test_modal_with_date_due_lights_filter_button(client, matter):
    client.post(
        reverse("matters:tasks-filter", args=[matter.id]),
        {"date_due_min": "2026-05-01"},
    )
    response = client.get(reverse("matters:tasks-index", args=[matter.id]))
    assert response.context["custom_filter_active"]


def test_importance_dropdown_does_not_light_filter_button(client, matter):
    client.post(reverse("matters:tasks-filter-importance", args=[matter.id, 7]))
    response = client.get(reverse("matters:tasks-index", args=[matter.id]))
    # Importance has its own dropdown indicator; Filter button stays off.
    assert response.context["custom_filter_active"] in (False, None, {})


def test_user_dropdown_does_not_light_filter_button(client, matter, user):
    client.post(reverse("matters:tasks-filter-user", args=[matter.id, user.id]))
    response = client.get(reverse("matters:tasks-index", args=[matter.id]))
    assert response.context["custom_filter_active"] in (False, None, {})


def test_modal_apply_strips_csrf_token_from_session(client, matter):
    client.post(
        reverse("matters:tasks-filter", args=[matter.id]),
        {"status": "Complete"},
    )
    session_filter = _session_for(client, "matter_tasks_filter")
    assert "csrfmiddlewaretoken" not in session_filter


def test_modal_apply_preserves_dropdown_state(client, matter):
    # Set an importance via the dropdown first.
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
