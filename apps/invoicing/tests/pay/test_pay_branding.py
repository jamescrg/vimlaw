"""The pay page renders one fixed look — Noto Sans, no serif, no per-firm theme.

Runs through the FakeProcessor (pay conftest pins it), so no network — the head's
font link renders regardless of processor. Colours live in css/pay.css (tokens),
so this only asserts the font choice + that the stylesheet is linked.
"""

import pytest
from django.test import Client
from django.urls import reverse

from utils.signing import make_payment_token

pytestmark = pytest.mark.django_db


def _render(sent_invoice):
    url = reverse("pay:invoice", kwargs={"token": make_payment_token(sent_invoice)})
    return Client().get(url).content.decode()


def test_pay_page_uses_noto_sans(sent_invoice):
    html = _render(sent_invoice)
    assert "Noto+Sans" in html
    assert "css/pay.css" in html
    # Single fixed look: the old serif option is gone entirely.
    assert "Noto+Serif" not in html
    assert "Noto Serif" not in html
    # No per-request inline :root theme block anymore (tokens are in pay.css).
    assert "--pay-gradient" not in html
