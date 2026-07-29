"""Absolute URLs for links that leave the app.

A link in an email has no request to borrow a host from, so anything built off
a background task falls back to the configured public base URL.
"""

from django.conf import settings


def absolute(path, request=None):
    """Absolutize a root-relative path using the request host when there is
    one, else settings.PUBLIC_BASE_URL. Returns the path unchanged if neither
    is available."""
    if request is not None:
        return request.build_absolute_uri(path)
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")
    return f"{base}{path}" if base else path
