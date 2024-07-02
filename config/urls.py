from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path, include

from apps.activity import views as activity
from apps.events import views as events
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
    # --------------------------------------
    # activity
    # --------------------------------------
    path("activity/", activity.index, name="activity-list"),
    path("activity/add", activity.add, name="activity-add"),
    path("activity/add_expense", activity.add_expense, name="activity-add-expense"),
    path("activity/add/<int:id>", activity.add, name="activity-add"),
    path(
        "activity/add_expense/<int:id>",
        activity.add_expense,
        name="activity-add-expense",
    ),
    path("activity/<int:id>/edit", activity.edit, name="activity-edit"),
    path(
        "activity/<int:id>/edit_expense",
        activity.edit_expense,
        name="activity-edit-expense",
    ),
    path("activity/<int:id>/delete", activity.delete, name="activity-delete"),
    path(
        "activity/<int:id>/delete_expense",
        activity.delete_expense,
        name="activity-delete-expense",
    ),
    path(
        "activity/<int:id>/toggle-entered",
        activity.toggle_entered,
        name="activity-toggle-entered",
    ),
    path(
        "activity/<int:id>/toggle-entered-expense",
        activity.toggle_entered_expense,
        name="activity-toggle-entered-expense",
    ),
    path("activity/filter", activity.filter, name="activity-filter"),
    path(
        "activity/filter/update", activity.filter_update, name="activity-filter-update"
    ),
    path(
        "activity/filter/<str:quick_filter>",
        activity.filter_quick,
        name="activity-filter-quick",
    ),
    path(
        "activity/filter/matter/<int:id>",
        activity.filter_matter,
        name="activity-filter-matter",
    ),
    path("activity/export", activity.export, name="activity-export"),
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
