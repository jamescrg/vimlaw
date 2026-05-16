"""Tests for the Filter-button / activity_period dropdown coherence on Unbilled.

The unbilled page has two filter surfaces: an activity_period quick-filter
dropdown (Current Month / Prior Month / Last Week / Last Month / All Activity)
and a Filter modal. The page's custom_filter_active correctly excludes
activity_period (the dropdown shows it), watching only last_invoice_before.
The fix here is the modal handler — it should preserve the activity_period
the user picked via the dropdown when the modal applies with that field blank.
"""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _session_for(client, key):
    return client.session.get(key, {})


def test_default_state_filter_button_off(client):
    response = client.get(reverse("invoicing:unbilled-index"))
    assert response.status_code == 200
    assert response.context["custom_filter_active"] in (False, None, {})


def test_activity_period_dropdown_does_not_light_filter_button(client):
    client.post(reverse("invoicing:unbilled-filter-period", args=["last_month"]))
    response = client.get(reverse("invoicing:unbilled-index"))
    assert response.context["activity_period"] == "last_month"
    # activity_period has its own dropdown indicator; Filter button stays off.
    assert response.context["custom_filter_active"] in (False, None, {})


def test_modal_with_last_invoice_before_lights_filter_button(client):
    client.post(
        reverse("invoicing:unbilled-filter"),
        {"last_invoice_before": "2026-01-01"},
    )
    response = client.get(reverse("invoicing:unbilled-index"))
    assert response.context["custom_filter_active"]


def test_modal_apply_preserves_dropdown_activity_period(client):
    """The user picks Last Month from the dropdown, then opens the modal and
    applies with only a last_invoice_before change — activity_period must
    survive the apply."""
    client.post(reverse("invoicing:unbilled-filter-period", args=["last_month"]))
    pre = _session_for(client, "unbilled_filter")
    assert pre.get("activity_period") == "last_month"

    # Apply the modal with last_invoice_before only; activity_period posted blank.
    client.post(
        reverse("invoicing:unbilled-filter"),
        {"last_invoice_before": "2026-01-01", "activity_period": ""},
    )
    post = _session_for(client, "unbilled_filter")
    assert post.get("activity_period") == "last_month"
    assert post.get("last_invoice_before") == "2026-01-01"


def test_modal_apply_can_override_activity_period_when_set(client):
    """When the modal posts a non-empty activity_period, it should still
    take effect — preservation only kicks in for the blank case."""
    client.post(reverse("invoicing:unbilled-filter-period", args=["last_month"]))
    client.post(
        reverse("invoicing:unbilled-filter"),
        {"last_invoice_before": "", "activity_period": "current_month"},
    )
    post = _session_for(client, "unbilled_filter")
    assert post.get("activity_period") == "current_month"
