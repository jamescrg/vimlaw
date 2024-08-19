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
    path("agenda/<int:task_id>/change-user", views.change_user, name="change-user"),
    path(
        "agenda/task-filter/",
        views.task_filter,
        name="filter-tasks",
    ),
    path(
        "agenda/filter-user/<str:user>/",
        views.quick_filter_user,
        name="filter-user",
    ),
]
