"""The pay page reflects the firm's payment font/background (Settings → Payments).

Runs through the FakeProcessor (pay conftest pins it), so no network — the head's
font link + inline CSS variables render regardless of processor.
"""

import pytest
from django.test import Client
from django.urls import reverse

from apps.settings.models import Company
from utils.signing import make_payment_token

pytestmark = pytest.mark.django_db


def _render(sent_invoice):
    url = reverse("pay:invoice", kwargs={"token": make_payment_token(sent_invoice)})
    return Client().get(url).content.decode()


def test_default_is_serif_gray(sent_invoice):
    # No Company row -> safe defaults.
    html = _render(sent_invoice)
    assert "Noto+Serif" in html
    assert '"Noto Serif", serif' in html
    assert "#d4d4d4" in html  # neutral-gray gradient stop (inline :root)


def test_sans_blue_applied(sent_invoice):
    Company.objects.create(name="Firm", payment_font="sans", payment_background="blue")
    html = _render(sent_invoice)
    assert "Noto+Sans" in html
    assert '"Noto Sans", sans-serif' in html
    assert "#cbd5e1" in html  # "blue" theme = slate; slate gradient stop (inline :root)
    # Serif is fully swapped out, not just added alongside.
    assert "Noto+Serif" not in html
    assert "Noto Serif" not in html
