from datetime import date, timedelta

from apps.agenda.events.models import Event
from apps.matters.proceedings.models import Proceeding


def get_event_data(matter):
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()
    pending_events = Event.objects.filter(matter=matter, status="Pending").order_by(
        "date"
    )

    third_day = date.today() + timedelta(days=3)
    past_events = (
        Event.objects.filter(matter=matter).exclude(status="Pending").order_by("-date")
    )

    event_data = {
        "matter": matter,
        "proceeding": proceeding,
        "pending_events": pending_events,
        "past_events": past_events,
        "third_day": third_day,
    }

    return event_data
