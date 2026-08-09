"""The auth_brand tag: firm logo on auth/error cards, Kosmos as fallback.

The tag renders on the login pages and every error page, including the 500
page, so it must degrade to the wordmark instead of raising when the firm
lookup fails.
"""

from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError
from django.template import loader

from apps.settings.models import Firm

pytestmark = pytest.mark.django_db

# Smallest valid GIF, enough for ImageField storage.
TINY_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00!\xf9\x04"
    b"\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D"
    b"\x01\x00;"
)


def render_error_page():
    # Contextless render, exactly how Django's 500 handler does it.
    return loader.get_template("500.html").render()


def test_firm_logo_replaces_wordmark(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    firm = Firm.objects.create(name="Craig Legal, LLC")
    firm.logo.save("logo.gif", SimpleUploadedFile("logo.gif", TINY_GIF))
    html = render_error_page()
    assert 'class="auth-title has-logo"' in html
    assert 'alt="Craig Legal, LLC"' in html
    assert firm.logo.url in html


def test_no_logo_falls_back_to_wordmark():
    Firm.objects.create(name="Craig Legal, LLC")
    html = render_error_page()
    assert "has-logo" not in html
    assert "Kosmos" in html


def test_dead_database_falls_back_to_wordmark():
    with patch("apps.settings.templatetags.firm_tags.Firm.objects") as objects:
        objects.first.side_effect = OperationalError("db is down")
        html = render_error_page()
    assert "has-logo" not in html
    assert "Kosmos" in html
