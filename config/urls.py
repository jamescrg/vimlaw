from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path, re_path
from django.views.static import serve

from apps.tasks.views import tasks_index
from config import health

# Override admin login to use 2FA
admin.site.login_url = "/accounts/login/"

urlpatterns = [
    path("health/live/", health.live, name="health-live"),
    path("health/ready/", health.ready, name="health-ready"),
    path("", tasks_index, name="tasks-index"),
    # Admin
    path("admin/", admin.site.urls),
    # Accounts App
    path("accounts/", include("apps.accounts.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    # Folders App
    path("", include("apps.folders.urls")),
    # Calendar App
    path("", include("apps.calendar.urls")),
    # Tasks App
    path("", include("apps.tasks.urls")),
    # Checklists App
    path("", include("apps.checklists.urls")),
    # Dash App
    path("", include("apps.dash.urls")),
    # Intakes App
    path("", include("apps.intakes.urls")),
    # Matters App
    path("", include("apps.matters.urls")),
    # Contacts App
    path("", include("apps.contacts.urls")),
    # Case App
    path("", include("apps.case.urls")),
    # Notes App
    path("", include("apps.notes.urls")),
    # Activity App
    path("", include("apps.activity.urls")),
    # Trust App
    path("", include("apps.trust.urls")),
    # Search App
    path("", include("apps.search.urls")),
    # Settings App
    path("", include("apps.settings.urls")),
    # Billing App
    path("", include("apps.invoicing.urls")),
    # Public, tokenized invoice payment page (no login)
    path("", include("apps.invoicing.pay.urls")),
    # Public, tokenized client intake form (no login)
    path("", include("apps.intakes.client_forms.public_urls")),
    # Reports App
    path("", include("apps.reports.urls")),
    # Management App
    path("", include("apps.management.urls")),
]

urlpatterns += staticfiles_urlpatterns()


def development_media_urlpatterns():
    """Serve local uploads only from Django's explicitly unsafe dev server."""
    if settings.DEBUG and settings.STORAGE_BACKEND == "local":
        return static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    return []


def public_branding_media_urlpatterns():
    """Keep media/company/ (the firm logo) routed in production.

    Unrouting MEDIA_ROOT protects confidential uploads, but the logo is
    deliberately public branding: the settings page, the public intake
    form pages, and invoice PDF generation all load it by URL. Only this
    one subdirectory - Firm.logo's upload_to - is exposed."""
    if settings.STORAGE_BACKEND == "local":
        media_prefix = settings.MEDIA_URL.lstrip("/")
        return [
            re_path(
                rf"^{media_prefix}company/(?P<path>.*)$",
                serve,
                {"document_root": settings.MEDIA_ROOT / "company"},
            )
        ]

    return []


urlpatterns += development_media_urlpatterns()
urlpatterns += public_branding_media_urlpatterns()
