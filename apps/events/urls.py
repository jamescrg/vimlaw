from django.urls import path

from apps.events.views import add, deadline_results, delete, edit, index

urlpatterns = [
    path("events/", index, name="events"),
    path("events/add", add, name="events-add"),
    path("events/add/<str:origin>", add, name="events-add-origin"),
    path(
        "events/deadline-results",
        deadline_results,
        name="events-deadline-results",
    ),
    path("events/add/<int:matter_id>", add, name="events-add-matter"),
    path(
        "events/add/<int:matter_id>/<str:origin>",
        add,
        name="events-add-matter-origin",
    ),
    path("events/<int:id>/edit", edit, name="events-edit"),
    path("events/<int:id>/edit/<str:origin>", edit, name="events-edit-origin"),
    path("events/<int:id>/delete", delete, name="events-delete"),
    path(
        "events/<int:id>/delete/<str:origin>",
        delete,
        name="events-delete-origin",
    ),
]
