from datetime import date

from apps.accounts.models import CustomUser
from apps.agenda.tasks.filter import TasksFilter
from apps.agenda.tasks.models import TaskNote, UserTaskNoteView
from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter


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

    pagination = CustomPaginator(
        tasks, per_page=20, request=request, session_key="tasks_pagination"
    )

    # Get user's note view history for badge notification system
    user_note_views = UserTaskNoteView.objects.filter(user=request.user).values(
        "task_id", "last_viewed_at"
    )
    view_times = {v["task_id"]: v["last_viewed_at"] for v in user_note_views}

    # Check each task for notes and new notes
    task_list = pagination.get_object_list()
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

    selected_matter = None
    if matter_id:
        selected_matter = Matter.objects.filter(id=matter_id).first()

    selected_user = None
    if user_id:
        selected_user = CustomUser.objects.filter(id=user_id).first()

    # Get current order (remove - prefix if exists)
    current_order = (
        filter_data.get("order_by", "priority") if filter_data else "priority"
    )
    current_order = current_order.lstrip("-")

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
        "priorities": list(range(1, 10)),
        "user_id": user_id,
        "matter_id": matter_id,
        "priority_value": priority_value,
        "selected_matter": selected_matter.name if selected_matter else "",
        "selected_user": selected_user.username.capitalize() if selected_user else "",
        "selected_priority": f"Priority {priority_value}" if priority_value else "",
        "filter_label": filter_data.get("filter_label", None) if filter_data else None,
        "current_order": current_order,
    }

    return list_data
