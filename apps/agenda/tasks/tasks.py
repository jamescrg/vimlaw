from django.core.paginator import Paginator

from apps.accounts.models import CustomUser
from apps.agenda.tasks.filter import TasksFilter
from apps.agenda.tasks.models import Task
from apps.events.filter import EventFilter
from apps.events.models import Event
from apps.matters.models import Matter


def get_table_data(request):
    table_data = {}

    tab = request.session.get("agenda_tab", "tasks")

    if tab == "tasks":
        filter_data = request.session.get("task_filter", None)

        if filter_data:
            filter = TasksFilter(filter_data)
            tasks = filter.qs
        else:
            tasks = Task.objects.all().order_by("-status", "description")
    elif tab == "events":
        filter_data = request.session.get("event_filter", None)

        if filter_data:
            filter = EventFilter(filter_data)
            events = filter.qs
        else:
            events = Event.objects.all().order_by("date")

    page = request.GET.get("page")
    pagination = Paginator(tasks if tab == "tasks" else events, 10).get_page(page)

    table_data["pagination"] = pagination
    table_data["objects"] = pagination.object_list
    table_data["matters"] = Matter.objects.filter(status="Open").order_by("name")
    table_data["users"] = CustomUser.objects.all().order_by("username")

    return table_data
