from django.urls import path

from apps.agenda.events.views import (
    events_add,
    events_deadline_results,
    events_delete,
    events_edit,
    events_filter,
    events_filter_quick,
    events_index,
    events_list,
)
from apps.agenda.tasks.views import (
    clear_tasks,
    tasks_add,
    tasks_add_quick,
    tasks_date,
    tasks_delete,
    tasks_edit,
    tasks_filter,
    tasks_filter_default,
    tasks_filter_focus,
    tasks_filter_matter,
    tasks_filter_quick,
    tasks_filter_sort,
    tasks_filter_user,
    tasks_focus,
    tasks_index,
    tasks_list,
    tasks_matter,
    tasks_priority,
    tasks_select,
    tasks_status,
    tasks_user,
)

app_name = "agenda"

urlpatterns = [
    path("", tasks_index, name="tasks-index"),
    path("agenda/tasks", tasks_select, name="tasks-select"),
    path("agenda/tasks/add", tasks_add, name="tasks-add"),
    path("agenda/tasks/add/quick", tasks_add_quick, name="tasks-add-quick"),
    path("agenda/tasks/<int:id>/edit", tasks_edit, name="tasks-edit"),
    path("agenda/tasks/<int:id>/delete", tasks_delete, name="tasks-delete"),
    path("agenda/tasks/<int:id>/task-status", tasks_status, name="tasks-task-status"),
    path(
        "agenda/tasks/<int:task_id>/task-priority/<int:priority>",
        tasks_priority,
        name="tasks-task-priority",
    ),
    path(
        "agenda/tasks/<int:task_id>/task-user/<int:user>",
        tasks_user,
        name="tasks-task-user",
    ),
    path(
        "agenda/tasks/<int:task_id>/task-focus/<str:focus>",
        tasks_focus,
        name="tasks-task-focus",
    ),
    path(
        "agenda/tasks/<int:task_id>/task-matter/<int:matter_id>",
        tasks_matter,
        name="tasks-task-matter",
    ),
    path("agenda/tasks/<int:task_id>/task-date", tasks_date, name="tasks-date"),
    path("agenda/tasks/filter/", tasks_filter, name="tasks-filter"),
    path("agenda/tasks/clear/", clear_tasks, name="tasks-clear"),
    path("agenda/tasks/list/", tasks_list, name="tasks-list"),
    path(
        "activity/tasks/filter/quick/<str:quick_filter>",
        tasks_filter_quick,
        name="tasks-filter-quick",
    ),
    path(
        "agenda/tasks/filter/matter/", tasks_filter_matter, name="tasks-filter-matter"
    ),
    path("agenda/tasks/filter/user/", tasks_filter_user, name="tasks-filter-user"),
    path("agenda/tasks/filter/focus/", tasks_filter_focus, name="tasks-filter-focus"),
    path(
        "agenda/tasks/filter/default/",
        tasks_filter_default,
        name="tasks-filter-default",
    ),
    path(
        "agenda/tasks/filter/sort/<str:order>/",
        tasks_filter_sort,
        name="tasks-filter-sort",
    ),
    path("events/", events_index, name="events-index"),
    path("events/list/", events_list, name="events-list"),
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
