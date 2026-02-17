from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path

from apps.agenda.tasks.views import tasks_index

# Override admin login to use 2FA
admin.site.login_url = "/accounts/login/"

urlpatterns = [
    path("", tasks_index, name="tasks-index"),
    # Admin
    path("admin/", admin.site.urls),
    # Accounts App
    path("accounts/", include("apps.accounts.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    # Folders App
    path("", include("apps.folders.urls")),
    # Agenda App
    path("", include("apps.agenda.urls")),
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
    # Reports App
    path("", include("apps.reports.urls")),
    # Lab App
    path("", include("apps.lab.urls")),
    # Management App
    path("", include("apps.management.urls")),
]

urlpatterns += staticfiles_urlpatterns()

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
