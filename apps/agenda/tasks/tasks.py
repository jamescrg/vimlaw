from django.core.paginator import Paginator

from apps.accounts.models import CustomUser
from apps.agenda.tasks.filter import TasksFilter
from apps.agenda.tasks.models import Task
from apps.matters.models import Matter


def get_table_data(request):
    table_data = {}

    filter_data = request.session.get("task_filter", None)

    if filter_data:
        filter = TasksFilter(filter_data)
        tasks = filter.qs
    else:
        tasks = Task.objects.all().order_by("-status", "description")

    page = request.GET.get("page")

    pagination = Paginator(tasks, per_page=10).get_page(page)

    table_data["pagination"] = pagination
    table_data["tasks"] = pagination.object_list
    table_data["matters"] = Matter.objects.filter(status="Open").order_by("name")
    table_data["users"] = CustomUser.objects.all().order_by("username")

    return table_data
