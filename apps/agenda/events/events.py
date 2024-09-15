from django.core.paginator import Paginator

from apps.accounts.models import CustomUser
from apps.agenda.events.filter import EventFilter
from apps.matters.models import Matter


def get_table_data(request):
    table_data = {}

    default_filter = {
        "status": "Pending",
        "matter": None,
        "date_min": "",
        "date_max": "",
        "party": None,
        "order_by": "date",
    }

    events_filter = request.session.get("events_filter", None)

    if events_filter:
        filter = EventFilter(events_filter)
        events = filter.qs
    else:
        filter = EventFilter(default_filter)
        events = filter.qs

    request.session["events_filter"] = filter.data
    request.session.modified = True

    page = request.GET.get("page")
    pagination = Paginator(events, 10).get_page(page)

    table_data["pagination"] = pagination
    table_data["objects"] = pagination.object_list
    table_data["matters"] = Matter.objects.filter(status="Open").order_by("name")
    table_data["users"] = CustomUser.objects.all().order_by("username")

    return table_data
