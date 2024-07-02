from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path, include

from apps.invoicing import views as invoicing
from apps.lab import views as lab
from apps.search import views as search
from apps.settings import views as settings
from apps.trust import views as trust

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
    # --------------------------------------
    # trust
    # --------------------------------------
    path("trust/", trust.index, name="trust"),
    path("trust/history/", trust.history, name="trust-history"),
    path("trust/history/<str:interval>/", trust.history, name="trust-history-interval"),
    path("trust/client/<int:id>", trust.client, name="trust-client"),
    path("trust/<int:contact_id>/add", trust.add, name="trust-add"),
    path("trust/<int:id>/edit", trust.edit, name="trust-edit"),
    path("trust/<int:id>/delete", trust.delete, name="trust-delete"),
    path("trust/<int:id>/entered", trust.toggle_entered, name="trust-entered"),
    path("trust/<int:id>/confirmed", trust.toggle_confirmed, name="trust-confirmed"),
    # --------------------------------------
    # search
    # --------------------------------------
    path("search/", search.index, name="search"),
    path("search/results", search.results, name="search-results"),
    # --------------------------------------
    # settings
    # --------------------------------------
    path("settings/", settings.index, name="settings"),
    path(
        "settings/google/login/<str:app>",
        settings.google_login,
        name="settings-google-login",
    ),
    path("settings/google/store", settings.google_store, name="settings-google-store"),
    path(
        "settings/google/logout/<str:app>",
        settings.google_logout,
        name="settings-google-logout",
    ),
    # --------------------------------------
    # invoicing
    # --------------------------------------
    path("invoicing/", invoicing.index, name="invoicing"),
    # --------------------------------------
    # lab
    # --------------------------------------
    path("lab/", lab.index, name="lab"),
    path("lab/results", lab.results, name="lab-results"),
    path("lab/email", lab.email_test, name="email-test"),
]

urlpatterns += staticfiles_urlpatterns()
