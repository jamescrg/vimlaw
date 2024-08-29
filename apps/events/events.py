from django.core.paginator import Paginator

from apps.accounts.models import CustomUser
from apps.events.filter import EventFilter
from apps.events.models import Event
from apps.matters.models import Matter


def get_table_data(request):

    table_data = {}

    events_filter = request.session.get("events_filter", None)

    if events_filter:
        filter = EventFilter(events_filter)
        events = filter.qs
        events = events.order_by("date")
    else:
        events = Event.objects.all().order_by("date")

    page = request.GET.get("page")
    pagination = Paginator(events, 10).get_page(page)

    table_data["pagination"] = pagination
    table_data["objects"] = pagination.object_list
    table_data["matters"] = Matter.objects.filter(status="Open").order_by("name")
    table_data["users"] = CustomUser.objects.all().order_by("username")

    return table_data
