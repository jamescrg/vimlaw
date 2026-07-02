"""Company settings subsections: Billing (payment appearance) + Research
(jurisdiction), and the payment-email style helper."""

import pytest
from pytest_django.asserts import assertTemplateUsed

from apps.settings.models import Company

pytestmark = pytest.mark.django_db


def test_company_page_has_all_sections(client):
    Company.objects.create(name="Firm")
    response = client.get("/settings/company/")
    assert response.status_code == 200
    assertTemplateUsed(response, "settings/company/index.html")
    content = response.content.decode()
    assert "Company Info" in content
    assert "Billing" in content
    assert "Research" in content


def test_payment_defaults_are_serif_gray():
    company = Company.objects.create(name="Firm")
    assert company.payment_font == "serif"
    assert company.payment_background == "gray"


def test_company_billing_saves_and_toasts(client):
    Company.objects.create(name="Firm")
    response = client.post(
        "/settings/company/billing/",
        {"payment_font": "sans", "payment_background": "blue"},
    )
    assert response.status_code == 200
    # Success is a toast (HX-Toast header), not inline body text.
    assert "success" in response.headers.get("HX-Toast", "").lower()
    company = Company.objects.first()
    assert company.payment_font == "sans"
    assert company.payment_background == "blue"


def test_company_research_saves_and_toasts(client):
    Company.objects.create(name="Firm")
    response = client.post(
        "/settings/company/research/",
        {"jurisdiction": "Montana"},
    )
    assert response.status_code == 200
    assert "success" in response.headers.get("HX-Toast", "").lower()
    assert Company.objects.first().jurisdiction == "Montana"


def test_payment_email_style_variants():
    from types import SimpleNamespace

    from utils.mail import payment_email_style

    serif = payment_email_style(
        SimpleNamespace(payment_font="serif", payment_background="gray")
    )
    assert "Noto Serif" in serif["email_font_family"]
    assert "#e5e5e5" in serif["email_bg_gradient"]

    sans = payment_email_style(
        SimpleNamespace(payment_font="sans", payment_background="blue")
    )
    assert "Noto Sans" in sans["email_font_family"]
    assert "Noto+Sans" in sans["email_font_link"]
    assert "#e2e8f0" in sans["email_bg_gradient"]  # "blue" = slate

    # None company -> safe serif/gray defaults (no crash).
    default = payment_email_style(None)
    assert "Noto Serif" in default["email_font_family"]
    assert "#e5e5e5" in default["email_bg_gradient"]
