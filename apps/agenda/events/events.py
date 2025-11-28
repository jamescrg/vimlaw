from datetime import datetime
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
        events, per_page=10, request=request, session_key="events_pagination"
    )

    # Calculate duration for each event
    event_list = pagination.get_object_list()
    for event in event_list:
        if event.start_time and event.end_time:
            # Combine times with a date to do time arithmetic
            start = datetime.combine(datetime.today(), event.start_time)
            end = datetime.combine(datetime.today(), event.end_time)
            duration_delta = end - start
            # Convert to hours (as a float for fractional hours)
            event.duration = duration_delta.total_seconds() / 3600
        else:
            event.duration = None

    current_order = filter.data.get("order_by", "date")
    if isinstance(current_order, list):
        current_order = current_order[0] if current_order else "date"
    current_order = current_order.lstrip("-")

    table_data["pagination"] = pagination
    table_data["session_key"] = "events_pagination"
    table_data["trigger_key"] = "eventsChanged"
    table_data["objects"] = event_list
    table_data["matters"] = Matter.objects.filter(
        status__in=["Pending", "Open"]
    ).order_by("name")
    table_data["users"] = CustomUser.objects.all().order_by("username")
    table_data["events_filter_status"] = filter.data.get("status")
    table_data["current_order"] = current_order

    return table_data
