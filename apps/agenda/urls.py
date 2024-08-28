from django.urls import path

from apps.agenda import views as agenda_views
from apps.agenda.tasks import views as tasks_views

app_name = "agenda"

urlpatterns = [
    path("agenda/", agenda_views.index, name="agenda"),
    path("agenda/set-tab/<str:tab>/", agenda_views.set_tab, name="set-tab"),
    path("agenda/add", tasks_views.add, name="add"),
    path("agenda/<int:id>/edit", tasks_views.edit, name="edit"),
    path("agenda/<int:id>/delete", tasks_views.delete, name="delete"),
    path("agenda/<int:id>/task-status", tasks_views.task_status, name="task-status"),
    path(
        "agenda/<int:task_id>/change-user", tasks_views.change_user, name="change-user"
    ),
    path(
        "agenda/task-filter/",
        tasks_views.task_filter,
        name="filter-tasks",
    ),
    path(
        "agenda/filter-user/<str:user>/",
        tasks_views.quick_filter_user,
        name="filter-user",
    ),
]
