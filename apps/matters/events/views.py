from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.agenda.events.models import Event
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding


@login_required
def index(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()
    pending_events = Event.objects.filter(matter=id, status="Pending").order_by("date")
    third_day = date.today() + timedelta(days=3)
    past_events = (
        Event.objects.filter(matter=id).exclude(status="Pending").order_by("-date")
    )

    context = {
        "app": "matters",
        "subapp": "events",
        "matter": matter,
        "proceeding": proceeding,
        "pending_events": pending_events,
        "past_events": past_events,
        "third_day": third_day,
    }

    return render(request, "matters/events/list.html", context)
