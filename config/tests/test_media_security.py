from django.test import override_settings
from django.urls import reverse

from config.urls import (
    development_media_urlpatterns,
    public_branding_media_urlpatterns,
)


@override_settings(DEBUG=False, STORAGE_BACKEND="local")
def test_local_media_is_not_publicly_routed_in_production():
    assert development_media_urlpatterns() == []


@override_settings(DEBUG=True, STORAGE_BACKEND="local")
def test_runserver_can_serve_local_media_in_development():
    assert development_media_urlpatterns()


@override_settings(DEBUG=True, STORAGE_BACKEND="s3")
def test_s3_media_is_never_mapped_to_local_media_root():
    assert development_media_urlpatterns() == []


@override_settings(DEBUG=False, STORAGE_BACKEND="local")
def test_firm_logo_media_stays_routed_in_production():
    """media/company/ holds only the firm logo (Firm.logo upload_to) - it is
    public branding used by the settings page, the public intake form pages,
    and invoice PDFs, so it survives the MEDIA_ROOT unrouting."""
    (pattern,) = public_branding_media_urlpatterns()
    assert pattern.resolve("media/company/logo.png")
    assert pattern.resolve("media/documents/1/secret.pdf") is None


@override_settings(STORAGE_BACKEND="s3")
def test_s3_branding_is_never_mapped_to_local_media_root():
    assert public_branding_media_urlpatterns() == []


def test_confidential_document_endpoints_require_authentication(client):
    download = client.get(reverse("case:documents-download", args=[123]))
    inline = client.get(reverse("case:serve", args=[123]))

    assert download.status_code == 302
    assert inline.status_code == 302
    assert download.url.startswith("/accounts/login/")
    assert inline.url.startswith("/accounts/login/")
