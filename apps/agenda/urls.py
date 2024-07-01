from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="agenda"),
    path("toggle-events", views.toggle_events, name="agenda-toggle-events"),
    path("add", views.add, name="agenda-add"),
    path("<int:id>/edit", views.edit, name="agenda-edit"),
    path("<int:id>/delete", views.delete, name="agenda-delete"),
    path("<int:id>/task-status", views.task_status, name="task-status"),
    path("filter", views.filter, name="agenda-filter"),
    path("filter/update", views.filter_update, name="agenda-filter-update"),
    path("filter/sort/<str:new_field>", views.filter_sort, name="agenda-filter-sort"),
    path(
        "filter/<str:quick_filter>",
        views.filter_quick,
        name="agenda-filter-quick",
    ),
    # path(
    #     "filter/matter/<int:id>",
    #     views.filter_matter,
    #     name="agenda-filter-matter",
    # ),
]
