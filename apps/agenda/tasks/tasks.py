from datetime import date

from django.core.paginator import Paginator

from apps.accounts.models import CustomUser
from apps.agenda.tasks.filter import TasksFilter
from apps.agenda.tasks.models import Task
from apps.matters.models import Matter


def get_table_data(request):
    table_data = {}

    today = date.today()

    filter_data = request.session.get("tasks_filter", None)

    if filter_data:
        filter = TasksFilter(filter_data)
        tasks = filter.qs
        user_id = filter_data.get("user")
        user_id = int(user_id) if user_id not in (None, "") else None

    else:
        tasks = Task.objects.all().order_by("-status", "priority")
        user_id = None

    page = request.GET.get("page")
    pagination = Paginator(tasks, 50).get_page(page)

    table_data = {
        "pagination": pagination,
        "objects": pagination.object_list,
        "matters": Matter.objects.filter(status="Open").order_by("name"),
        "today": today,
        "users": CustomUser.objects.filter(is_active=True).order_by("username"),
        "user_id": user_id,
    }

    return table_data
