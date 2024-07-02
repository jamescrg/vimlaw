from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path

urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),
    # Accounts App
    path("accounts/", include("apps.accounts.urls")),
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
    # Events App
    path("", include("apps.events.urls")),
    # Activity App
    path("", include("apps.activity.urls")),
    # Trust App
    path("", include("apps.trust.urls")),
    # Search App
    path("", include("apps.search.urls")),
    # Settings App
    path("", include("apps.settings.urls")),
    # Invoicing App
    path("", include("apps.invoicing.urls")),
    # Lab App
    path("", include("apps.lab.urls")),
]

urlpatterns += staticfiles_urlpatterns()
