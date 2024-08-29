from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path

from apps.agenda.tasks.views import tasks_list

urlpatterns = [
    path("", tasks_list, name="home-index"),
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
    # Billing App
    path("", include("apps.billing.urls")),
    # Lab App
    path("", include("apps.lab.urls")),
]

urlpatterns += staticfiles_urlpatterns()

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
