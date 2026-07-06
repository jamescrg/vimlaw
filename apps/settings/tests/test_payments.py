"""Firm settings: one unified form (contact details, invoice BCC, research
jurisdiction, logo) saved together.

The former Billing subsection (per-firm payment font/background) was removed when
the payment page + emails collapsed to a single fixed look (gray/white/Noto Sans).
The former separate Research subsection/endpoint was folded into this one form.
"""

import pytest
from pytest_django.asserts import assertTemplateUsed

from apps.settings.models import Firm

pytestmark = pytest.mark.django_db


def test_firm_page_renders_single_form(client):
    Firm.objects.create(name="Firm")
    response = client.get("/settings/firm/")
    assert response.status_code == 200
    assertTemplateUsed(response, "settings/firm/index.html")
    content = response.content.decode()
    # One save button, and the merged research field is on the same form.
    assert "Save Firm Details" in content
    assert "id_jurisdiction" in content
    assert "id_billing_email" in content
    # The removed payment-appearance subsection left no Save button of its own.
    assert content.count("Save Firm Details") == 1


def test_firm_form_saves_jurisdiction_and_toasts(client):
    Firm.objects.create(name="Firm")
    response = client.post(
        "/settings/firm/",
        {"name": "Firm", "jurisdiction": "Montana"},
    )
    assert response.status_code == 200
    assert "success" in response.headers.get("HX-Toast", "").lower()
    assert Firm.objects.first().jurisdiction == "Montana"


def test_firm_form_normalizes_phone(client):
    Firm.objects.create(name="Firm")
    response = client.post(
        "/settings/firm/",
        {"name": "Firm", "phone": "(406) 555-1234"},
    )
    assert response.status_code == 200
    assert Firm.objects.first().phone == "4065551234"


def test_firm_details_save_toasts_and_leaves_logo_alone(client):
    """The logo is decoupled from the details form: saving details still fires
    the success toast and never touches an existing logo."""
    Firm.objects.create(name="Firm", logo="company/existing.png")
    response = client.post("/settings/firm/", {"name": "Firm", "city": "Helena"})
    assert response.status_code == 200
    # The "Firm details updated" toast is preserved.
    assert "success" in response.headers.get("HX-Toast", "").lower()
    firm = Firm.objects.first()
    assert firm.city == "Helena"
    assert firm.logo.name == "company/existing.png"


def test_firm_logo_upload_rejects_non_image(client):
    """A bad upload is rejected by the logo endpoint without saving anything."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    Firm.objects.create(name="Firm")
    bad = SimpleUploadedFile("logo.txt", b"not an image", content_type="text/plain")
    response = client.post("/settings/firm/logo/upload/", {"logo": bad})
    assert response.status_code == 200
    assert not Firm.objects.first().logo
    assert "errorlist" in response.content.decode()
