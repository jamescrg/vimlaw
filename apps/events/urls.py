from django.urls import path

from apps.events.views import (
    add,
    deadline_results,
    delete,
    edit,
    event_filter,
    index,
    quick_filter_pending,
)

app_name = "events"

urlpatterns = [
    path("events/", index, name="events"),
    path("events/add", add, name="add"),
    path("events/add/<str:origin>", add, name="add-origin"),
    path(
        "events/deadline-results",
        deadline_results,
        name="deadline-results",
    ),
    path("events/add/<int:matter_id>", add, name="add-matter"),
    path(
        "events/add/<int:matter_id>/<str:origin>",
        add,
        name="add-matter-origin",
    ),
    path("events/<int:id>/edit", edit, name="edit"),
    path("events/<int:id>/edit/<str:origin>", edit, name="edit-origin"),
    path("events/<int:id>/delete", delete, name="delete"),
    path(
        "events/<int:id>/delete/<str:origin>",
        delete,
        name="delete-origin",
    ),
    path("events/filter-events/", event_filter, name="filter-events"),
    path(
        "events/quick-filter-pending/",
        quick_filter_pending,
        name="quick-filter-pending",
    ),
]
