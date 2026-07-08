from django.urls import path

from apps.calendar.views import (
    events_add,
    events_api,
    events_calendar,
    events_deadline_form,
    events_deadline_modal,
    events_deadline_results,
    events_delete,
    events_edit,
    events_filter,
    events_filter_assigned,
    events_filter_matter,
    events_filter_quick,
    events_filter_sort,
    events_filter_status,
    events_index,
    events_list,
    events_quick_update,
    events_select,
    events_view_mode,
)

app_name = "calendar"

urlpatterns = [
    path("events/", events_index, name="index"),
    path("events/list/", events_list, name="list"),
    path("events/calendar/", events_calendar, name="calendar"),
    path("events/api/", events_api, name="api"),
    path("events/api/matter/<int:matter_id>", events_api, name="api-matter"),
    path("events/<int:id>/quick-update", events_quick_update, name="quick-update"),
    path("events/view/<str:mode>", events_view_mode, name="view-mode"),
    path("events/select", events_select, name="select"),
    path("events/add", events_add, name="add"),
    path("events/add/<str:origin>", events_add, name="add-origin"),
    path(
        "events/deadline-results",
        events_deadline_results,
        name="deadline-results",
    ),
    path(
        "events/deadline-form",
        events_deadline_form,
        name="deadline-form",
    ),
    path(
        "events/deadline-calculator",
        events_deadline_modal,
        name="deadline-modal",
    ),
    path("events/add/<int:matter_id>", events_add, name="add-matter"),
    path(
        "events/add/<int:matter_id>/<str:origin>",
        events_add,
        name="add-matter-origin",
    ),
    path("events/<int:id>/edit", events_edit, name="edit"),
    path("events/<int:id>/edit/<str:origin>", events_edit, name="edit-origin"),
    path("events/<int:id>/delete", events_delete, name="delete"),
    path(
        "events/<int:id>/delete/<str:origin>",
        events_delete,
        name="delete-origin",
    ),
    path("events/filter/", events_filter, name="filter"),
    path(
        "events/filter/quick/<str:quick_filter>",
        events_filter_quick,
        name="filter-quick",
    ),
    path(
        "events/filter/status/",
        events_filter_status,
        {"status": ""},
        name="filter-status-all",
    ),
    path(
        "events/filter/status/<str:status>",
        events_filter_status,
        name="filter-status",
    ),
    path(
        "events/filter/sort/<str:order>",
        events_filter_sort,
        name="filter-sort",
    ),
    path(
        "events/filter/assigned/",
        events_filter_assigned,
        {"assigned": ""},
        name="filter-assigned-all",
    ),
    path(
        "events/filter/assigned/<str:assigned>",
        events_filter_assigned,
        name="filter-assigned",
    ),
    path(
        "events/filter/matter/",
        events_filter_matter,
        {"matter": ""},
        name="filter-matter-all",
    ),
    path(
        "events/filter/matter/<str:matter>",
        events_filter_matter,
        name="filter-matter",
    ),
]
