from django.urls import path

from . import views

app_name = "agenda"

urlpatterns = [
    path("agenda/", views.index, name="agenda"),
    path("agenda/toggle-events", views.toggle_events, name="toggle-events"),
    path("agenda/add", views.add, name="add"),
    path("agenda/<int:id>/edit", views.edit, name="edit"),
    path("agenda/<int:id>/delete", views.delete, name="delete"),
    path("agenda/<int:id>/task-status", views.task_status, name="task-status"),
    path("agenda/filter", views.filter, name="filter"),
    path("agenda/filter/update", views.filter_update, name="filter-update"),
    path(
        "agenda/filter/sort/<str:new_field>",
        views.filter_sort,
        name="filter-sort",
    ),
    path(
        "agenda/filter/<str:quick_filter>",
        views.filter_quick,
        name="filter-quick",
    ),
    # path(
    #     "filter/matter/<int:id>",
    #     views.filter_matter,
    #     name="filter-matter",
    # ),
]
