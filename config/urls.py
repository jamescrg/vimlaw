from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import path, include

from apps.activity import views as activity
from apps.agenda import views as agenda
from apps.contacts import views as contacts
from apps.events import views as events
from apps.intakes import views as intakes
from apps.invoicing import views as invoicing
from apps.lab import views as lab
from apps.matters import views as matters
from apps.matters import views_activity as matters_activity
from apps.matters import views_contacts as matters_contacts
from apps.matters import views_events as matters_events
from apps.matters import views_proceedings as matters_proceedings
from apps.matters import views_rates as matters_rates
from apps.matters import views_settlement as matters_settlement
from apps.matters import views_timeline as matters_timeline
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
    # --------------------------------------
    # intakes
    # --------------------------------------
    path("intakes/", intakes.index, name="intakes-list"),
    path("intakes/list/data", intakes.list_data, name="intakes-list-data"),
    path("intakes/<int:id>", intakes.detail, name="intakes-detail"),
    path("intakes/<int:id>/data", intakes.detail_data, name="intakes-detail-data"),
    path("intakes/add", intakes.add, name="intakes-add"),
    path("intakes/<int:id>/edit", intakes.edit, name="intakes-edit"),
    path("intakes/<int:id>/delete", intakes.delete, name="intakes-delete"),
    path("intakes/filter", intakes.filter, name="intakes-filter"),
    path("intakes/filter/update", intakes.filter_update, name="intakes-filter-update"),
    path(
        "intakes/filter/<str:quick_filter>",
        intakes.filter_quick,
        name="intakes-filter-quick",
    ),
    path("intakes/sort/<str:order>", intakes.order, name="intakes-sort-by"),
    path("intakes/<int:id>/add-note", intakes.add_note, name="intakes-add_note"),
    path("intakes/<int:id>/edit-note", intakes.edit_note, name="intakes-edit_note"),
    path(
        "intakes/<int:id>/delete-note", intakes.delete_note, name="intakes-delete_note"
    ),
    # --------------------------------------
    # matters
    # --------------------------------------
    path("matters/", matters.index, name="matters-list"),
    path("matters/<int:id>", matters.detail, name="matters-detail"),
    path("matters/add", matters.add, name="matters-add"),
    path("matters/<int:id>/edit", matters.edit, name="matters-edit"),
    path("matters/<int:id>/delete", matters.delete, name="matters-delete"),
    path("matters/filter", matters.filter, name="matters-filter"),
    path("matters/filter/update", matters.filter_update, name="matters-filter-update"),
    path(
        "matters/filter/<str:quick_filter>",
        matters.filter_quick,
        name="matters-filter-quick",
    ),
    path("matters/sort/<str:order>", matters.order, name="matters-sort-by"),
    path(
        "matters/<int:id>/edit-description",
        matters.edit_description,
        name="matters-edit-description",
    ),
    path("matters/<int:id>/print", matters.print, name="matters-print"),
    # matters-contacts
    path("matters/<int:id>/contacts", matters_contacts.index, name="matters-contacts"),
    path(
        "matters/<int:id>/contacts/assign",
        matters_contacts.assign,
        name="matters-contacts-assign",
    ),
    path(
        "matters/<int:id>/contacts/assign/results",
        matters_contacts.assign_results,
        name="matters-contacts-assign-results",
    ),
    path(
        "matters/<int:id>/assign/<int:contact_id>",
        matters_contacts.assign_role,
        name="matters-contacts-assign-role",
    ),
    path(
        "matters/assign/store",
        matters_contacts.assign_store,
        name="matters-contacts-assign-store",
    ),
    path(
        "matters/assign/<id>/edit",
        matters_contacts.assign_edit,
        name="matters-contacts-assign-edit",
    ),
    path(
        "matters/assign/<id>/update",
        matters_contacts.assign_update,
        name="matters-contacts-assign-update",
    ),
    path(
        "matters/assign/<id>/delete",
        matters_contacts.assign_delete,
        name="matters-contacts-assign-delete",
    ),
    # matters-rates
    path("matters/<int:id>/rates", matters_rates.index, name="matters-rates"),
    path(
        "matters/<int:id>/rates/add",
        matters_rates.add,
        name="matters-rates-add",
    ),
    path(
        "matters/<int:id>/rates/<int:rate_id>/edit",
        matters_rates.edit,
        name="matters-rates-edit",
    ),
    path(
        "matters/<int:id>/rates/<int:rate_id>/delete",
        matters_rates.delete,
        name="matters-rates-delete",
    ),
    # matters-activity
    path("matters/<int:id>/activity", matters_activity.index, name="matters-activity"),
    # matters-events
    path("matters/<int:id>/events", matters_events.index, name="matters-events"),
    # matters-proceedings
    path(
        "matters/<int:id>/proceedings",
        matters_proceedings.index,
        name="matters-proceedings",
    ),
    path(
        "matters/<int:id>/proceedings/add",
        matters_proceedings.add,
        name="matters-proceedings-add",
    ),
    path(
        "matters/<int:id>/proceedings/<int:proceeding_id>/edit",
        matters_proceedings.edit,
        name="matters-proceedings-edit",
    ),
    path(
        "matters/<int:id>/proceedings/<int:proceeding_id>/delete",
        matters_proceedings.delete,
        name="matters-proceedings-delete",
    ),
    # matters-settlement
    path(
        "matters/<int:id>/settlement",
        matters_settlement.index,
        name="matters-settlement",
    ),
    path(
        "matters/<int:id>/settlement/add",
        matters_settlement.add,
        name="matters-settlement-add",
    ),
    path(
        "matters/<int:id>/settlement/<int:entry_id>/edit",
        matters_settlement.edit,
        name="matters-settlement-edit",
    ),
    path(
        "matters/<int:id>/settlement/<int:entry_id>/delete",
        matters_settlement.delete,
        name="matters-settlement-delete",
    ),
    # matters-timeline
    path("matters/<int:id>/timeline", matters_timeline.index, name="matters-timeline"),
    path(
        "matters/<int:id>/timeline/add",
        matters_timeline.add,
        name="matters-timeline-add",
    ),
    path(
        "matters/<int:id>/timeline/<int:fact_id>/edit",
        matters_timeline.edit,
        name="matters-timeline-edit",
    ),
    path(
        "matters/<int:id>/timeline/<int:fact_id>/delete",
        matters_timeline.delete,
        name="matters-timeline-delete",
    ),
    path(
        "matters/<int:id>/timeline/print",
        matters_timeline.print,
        name="matters-timeline-print",
    ),
    # --------------------------------------
    # contacts
    # --------------------------------------
    path("contacts/", contacts.index, name="contacts"),
    path("contacts/<int:id>", contacts.select, name="contacts-select"),
    path("contacts/add", contacts.add, name="contacts-add"),
    path("contacts/<int:id>/edit", contacts.edit, name="contacts-edit"),
    path("contacts/<int:id>/delete", contacts.delete, name="contacts-delete"),
    path("contacts/<int:id>/assign", contacts.assign, name="contacts-assign"),
    path(
        "contacts/<int:id>/assign/store",
        contacts.assign_store,
        name="contacts-assign-store",
    ),
    path("contacts/<int:id>/remove", contacts.remove, name="contacts-remove"),
    path(
        "contacts/<int:id>/remove/store",
        contacts.remove_store,
        name="contacts-remove-store",
    ),
    path(
        "contacts/<int:id>/add_intake", contacts.add_intake, name="contacts-add-intake"
    ),
    path(
        "contacts/<int:id>/toggle_google_sync",
        contacts.toggle_google_sync,
        name="contacts-toggle-google-sync",
    ),
    path("contacts/google_list", contacts.google_list, name="contacts-google"),
    # --------------------------------------
    # events
    # --------------------------------------
    path("events/", events.index, name="events"),
    path("events/add", events.add, name="events-add"),
    path("events/add/<str:origin>", events.add, name="events-add-origin"),
    path(
        "events/deadline-results",
        events.deadline_results,
        name="events-deadline-results",
    ),
    path("events/add/<int:matter_id>", events.add, name="events-add-matter"),
    path(
        "events/add/<int:matter_id>/<str:origin>",
        events.add,
        name="events-add-matter-origin",
    ),
    path("events/<int:id>/edit", events.edit, name="events-edit"),
    path("events/<int:id>/edit/<str:origin>", events.edit, name="events-edit-origin"),
    path("events/<int:id>/delete", events.delete, name="events-delete"),
    path(
        "events/<int:id>/delete/<str:origin>",
        events.delete,
        name="events-delete-origin",
    ),
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
