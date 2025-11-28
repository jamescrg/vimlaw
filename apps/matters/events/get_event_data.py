from datetime import date, datetime, timedelta

from apps.agenda.events.models import Event
from apps.matters.proceedings.models import Proceeding


def get_event_data(request, matter):
    proceeding = Proceeding.objects.filter(matter=matter.id, primary=True).first()
    third_day = date.today() + timedelta(days=3)

    # Get filter status from session, default to "Pending"
    status_session_key = f"matter_events_filter_{matter.id}"
    filter_status = request.session.get(status_session_key, "Pending")

    # Get sort order from session, default to "date"
    sort_session_key = f"matter_events_sort_{matter.id}"
    order_by = request.session.get(sort_session_key, "date")

    # Build queryset based on filter
    events = Event.objects.filter(matter=matter)
    if filter_status:
        events = events.filter(status=filter_status)

    # Apply sort order (supports multiple fields separated by comma)
    order_fields = [f.strip() for f in order_by.split(",")]
    events = events.order_by(*order_fields)

    # Calculate duration for events
    for event in events:
        if event.start_time and event.end_time:
            start = datetime.combine(datetime.today(), event.start_time)
            end = datetime.combine(datetime.today(), event.end_time)
            duration_delta = end - start
            event.duration = duration_delta.total_seconds() / 3600
        else:
            event.duration = None

    # Get current order without the "-" prefix for template comparison
    # Use the first field for highlighting the active sort button
    first_order = order_fields[0] if order_fields else "date"
    current_order = first_order.lstrip("-")

    event_data = {
        "matter": matter,
        "proceeding": proceeding,
        "events": events,
        "events_filter_status": filter_status,
        "current_order": current_order,
        "third_day": third_day,
    }

    return event_data
