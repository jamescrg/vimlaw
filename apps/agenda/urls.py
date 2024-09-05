from django.urls import path

from apps.agenda.tasks.views import (
    tasks_add,
    tasks_delete,
    tasks_edit,
    tasks_filter,
    tasks_filter_quick,
    tasks_filter_sort,
    tasks_filter_user,
    tasks_list,
    tasks_select,
    tasks_status,
)

app_name = "agenda"

urlpatterns = [
    path("agenda/", tasks_list, name="tasks-list"),
    path("agenda/tasks", tasks_select, name="tasks-select"),
    path("agenda/tasks/add", tasks_add, name="tasks-add"),
    path("agenda/tasks/<int:id>/edit", tasks_edit, name="tasks-edit"),
    path("agenda/tasks/<int:id>/delete", tasks_delete, name="tasks-delete"),
    path("agenda/tasks/<int:id>/task-status", tasks_status, name="tasks-task-status"),
    path("agenda/tasks/filter/", tasks_filter, name="tasks-filter"),
    path(
        "activity/tasks/filter/quick/<str:quick_filter>",
        tasks_filter_quick,
        name="tasks-filter-quick",
    ),
    path("agenda/tasks/filter/user/", tasks_filter_user, name="tasks-filter-user"),
    path(
        "agenda/tasks/filter/sort/<str:order>/",
        tasks_filter_sort,
        name="tasks-filter-sort",
    ),
]
