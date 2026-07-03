"""Company settings subsections: Company Info + Research (jurisdiction).

The former Billing subsection (per-firm payment font/background) was removed when
the payment page + emails collapsed to a single fixed look (gray/white/Noto Sans).
"""

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
    assert "Research" in content
    # Billing (payment appearance) was removed.
    assert "Billing" not in content


def test_company_research_saves_and_toasts(client):
    Company.objects.create(name="Firm")
    response = client.post(
        "/settings/company/research/",
        {"jurisdiction": "Montana"},
    )
    assert response.status_code == 200
    assert "success" in response.headers.get("HX-Toast", "").lower()
    assert Company.objects.first().jurisdiction == "Montana"
