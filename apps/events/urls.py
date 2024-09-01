from django.urls import path

from apps.events.views import (
    events_add,
    events_deadline_results,
    events_delete,
    events_edit,
    events_filter,
    events_filter_quick,
    events_list,
)

app_name = "events"

urlpatterns = [
    path("events/", events_list, name="events-list"),
    path("events/add", events_add, name="events-add"),
    path("events/add/<str:origin>", events_add, name="events-add-origin"),
    path(
        "events/deadline-results",
        events_deadline_results,
        name="events-deadline-results",
    ),
    path("events/add/<int:matter_id>", events_add, name="events-add-matter"),
    path(
        "events/add/<int:matter_id>/<str:origin>",
        events_add,
        name="events-add-matter-origin",
    ),
    path("events/<int:id>/edit", events_edit, name="events-edit"),
    path("events/<int:id>/edit/<str:origin>", events_edit, name="events-edit-origin"),
    path("events/<int:id>/delete", events_delete, name="events-delete"),
    path(
        "events/<int:id>/delete/<str:origin>",
        events_delete,
        name="events-delete-origin",
    ),
    path("events/filter/", events_filter, name="events-filter"),
    path(
        "events/filter/quick/<str:quick_filter>",
        events_filter_quick,
        name="events-filter-quick",
    ),
]
