from datetime import date

from apps.accounts.models import CustomUser
from apps.management.pagination import CustomPaginator
from apps.management.selection import (
    all_visible_selected,
    get_selected_ids,
    get_session_key,
)
from apps.matters.models import Matter
from apps.tasks.filter import TasksFilter
from apps.tasks.models import (
    Checklist,
    Task,
    TaskNote,
    UserChecklistView,
    UserTaskNoteView,
)


def get_list_data(request):
    list_data = {}

    today = date.today()

    filter_data = request.session.get("tasks_filter", {})

    if filter_data:
        filter_data = {
            **filter_data,
            "status": filter_data.get("status", "Pending"),
            "order_by": filter_data.get("order_by", "priority"),
        }

        filter = TasksFilter(filter_data)
        tasks = filter.qs

        user_id = filter_data.get("user")
        user_id = int(user_id) if user_id not in (None, "") else None

        matter_id = filter_data.get("matter")
        matter_id = int(matter_id) if matter_id not in (None, "") else None

        priority_value = filter_data.get("priority")
        priority_value = (
            int(priority_value) if priority_value not in (None, "", 0) else None
        )

    else:
        default_filter = {
            "status": "Pending",
            "matter": None,
            "order_by": "priority",
            "user": request.user.id,
        }

        filter = TasksFilter(default_filter)
        tasks = filter.qs

        user_id = request.user.id
        matter_id = None
        priority_value = None

    # Force-show newly created tasks at the top regardless of filters
    new_task_ids = request.session.pop("new_task_ids", [])
    edited_task_ids = request.session.pop("edited_task_ids", [])

    # Exclude new tasks from main queryset to avoid duplicates
    if new_task_ids:
        tasks = tasks.exclude(id__in=new_task_ids)

    pagination = CustomPaginator(
        tasks, per_page=20, request=request, session_key="tasks_pagination"
    )

    # Get user's note view history for badge notification system
    user_note_views = UserTaskNoteView.objects.filter(user=request.user).values(
        "task_id", "last_viewed_at"
    )
    view_times = {v["task_id"]: v["last_viewed_at"] for v in user_note_views}

    # Prepend new tasks to the top of the page
    if new_task_ids:
        new_tasks = list(Task.objects.filter(id__in=new_task_ids))
        task_list = new_tasks + list(pagination.get_object_list())
    else:
        task_list = pagination.get_object_list()

    # Bulk-prefetch checklists to avoid N+1
    task_ids = [t.id for t in task_list]
    checklists = Checklist.objects.filter(task_id__in=task_ids).prefetch_related(
        "items"
    )
    checklists_by_task = {cl.task_id: cl for cl in checklists}

    # Checklist view tracking
    checklist_views = UserChecklistView.objects.filter(
        user=request.user, task_id__in=task_ids
    ).values_list("task_id", flat=True)
    viewed_checklist_task_ids = set(checklist_views)

    for task in task_list:
        task.has_notes = task.notes.exists()
        if task.has_notes:
            last_viewed = view_times.get(task.id)
            if last_viewed:
                # Check if there are notes created after last view by other users
                task.has_new_notes = (
                    TaskNote.objects.filter(task=task, created_at__gt=last_viewed)
                    .exclude(user=request.user)
                    .exists()
                )
            else:
                # Never viewed - show as new if there are notes by other users
                task.has_new_notes = (
                    TaskNote.objects.filter(task=task)
                    .exclude(user=request.user)
                    .exists()
                )
        else:
            task.has_new_notes = False

        cl = checklists_by_task.get(task.id)
        if cl:
            task.has_checklist = True
            items = cl.items.all()
            task.checklist_total = len(items)
            task.checklist_done = sum(1 for i in items if i.is_complete)
            task.checklist_complete = task.checklist_done == task.checklist_total
            task.has_unviewed_checklist = task.id not in viewed_checklist_task_ids
        else:
            task.has_checklist = False
            task.has_unviewed_checklist = False

    selected_matter = None
    if matter_id:
        selected_matter = Matter.objects.filter(id=matter_id).first()

    selected_user = None
    if user_id:
        selected_user = CustomUser.objects.filter(id=user_id).first()

    # Get current order (remove - prefix if exists)
    current_order = (
        (filter_data.get("order_by") or "priority") if filter_data else "priority"
    )
    current_order = current_order.lstrip("-")

    # Selection state
    selected_session_key = get_session_key("selected_tasks")
    selected_tasks = get_selected_ids(request, selected_session_key)
    visible_ids = [task.id for task in task_list]
    all_selected = all_visible_selected(selected_tasks, visible_ids)

    list_data = {
        "pagination": pagination,
        "session_key": "tasks_pagination",
        "trigger_key": "tasksListChanged",
        "objects": task_list,
        "matters": Matter.objects.filter(status__in=["Pending", "Open"]).order_by(
            "name"
        ),
        "today": today,
        "users": CustomUser.objects.filter(is_active=True).order_by("username"),
        "priorities": list(range(1, 11)),
        "user_id": user_id,
        "matter_id": matter_id,
        "priority_value": priority_value,
        "selected_matter": selected_matter.name if selected_matter else "",
        "selected_user": selected_user.username.capitalize() if selected_user else "",
        "selected_priority": f"Priority {priority_value}" if priority_value else "",
        "filter_label": filter_data.get("filter_label", None) if filter_data else None,
        "current_order": current_order,
        "selected_tasks": selected_tasks,
        "all_selected": all_selected,
        "new_task_ids": new_task_ids,
        "edited_task_ids": edited_task_ids,
    }

    return list_data
