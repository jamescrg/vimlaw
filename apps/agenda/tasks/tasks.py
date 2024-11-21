from datetime import date

from apps.accounts.models import CustomUser
from apps.agenda.tasks.filter import TasksFilter
from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter


def get_list_data(request):
    list_data = {}

    default_filter = {
        "status": None,
        "matter": None,
        "order_by": "priority",
    }

    today = date.today()

    filter_data = request.session.get("tasks_filter", {})

    if filter_data:
        filter = TasksFilter(filter_data)
        tasks = filter.qs
        user_id = filter_data.get("user")
        user_id = int(user_id) if user_id not in (None, "") else None

    else:
        filter = TasksFilter(default_filter)
        tasks = filter.qs
        user_id = None

    pagination = CustomPaginator(
        tasks, per_page=10, request=request, session_key="tasks_pagination"
    )

    list_data = {
        "pagination": pagination,
        "session_key": "tasks_pagination",
        "trigger_key": "tasksListChanged",
        "objects": pagination.get_object_list(),
        "matters": Matter.objects.filter(status="Open").order_by("name"),
        "today": today,
        "users": CustomUser.objects.filter(is_active=True).order_by("username"),
        "user_id": user_id,
    }

    return list_data
