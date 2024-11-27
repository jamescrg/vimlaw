from logging import getLogger

from apps.accounts.models import CustomUser
from apps.agenda.events.filter import EventFilter
from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter

logger = getLogger(__name__)


def get_table_data(request):
    # if google.check_credentials():
    #     try:
    #         google.remove_deleted_events()
    #     except Exception as err:
    #         logger.error(f"Error removing deleted events: {err}")
    table_data = {}

    default_filter = {
        "status": "Pending",
        "matter": None,
        "date_min": "",
        "date_max": "",
        "party": None,
        "order_by": "date",
    }

    events_filter = request.session.get("events_filter", {})

    if events_filter:
        filter = EventFilter(events_filter)
        events = filter.qs
    else:
        filter = EventFilter(default_filter)
        events = filter.qs

    request.session["events_filter"] = filter.data
    request.session.modified = True

    pagination = CustomPaginator(
        events, per_page=4, request=request, session_key="events_pagination"
    )

    table_data["pagination"] = pagination
    table_data["session_key"] = "events_pagination"
    table_data["trigger_key"] = "eventsChanged"
    table_data["objects"] = pagination.get_object_list()
    table_data["matters"] = Matter.objects.filter(status="Open").order_by("name")
    table_data["users"] = CustomUser.objects.all().order_by("username")

    return table_data
