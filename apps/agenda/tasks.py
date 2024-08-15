from apps.accounts.models import CustomUser
from apps.agenda.filter_tasks import TasksFilter
from apps.agenda.models import Task
from apps.matters.models import Matter


def get_table_data(request):
    table_data = {}

    filter_data = request.session.get("task_filter", None)

    if filter_data:
        filter = TasksFilter(filter_data)
        tasks = filter.qs
    else:
        tasks = Task.objects.all().order_by("-status", "description")

    table_data["tasks"] = tasks
    table_data["matters"] = Matter.objects.filter(status="Open").order_by("name")
    table_data["users"] = CustomUser.objects.all().order_by("username")

    return table_data
