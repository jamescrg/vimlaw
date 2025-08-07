from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.matters.events.get_event_data import get_event_data
from apps.matters.models import Matter


@login_required
def events_index(request, id):
    matter = get_object_or_404(Matter, pk=id)

    event_data = get_event_data(matter)

    context = {
        "app": "matters",
        "subapp": "events",
        "matter": matter,
    } | event_data

    return render(request, "matters/events/main.html", context)


@login_required
def events_list(request, id):
    matter = get_object_or_404(Matter, pk=id)

    event_data = get_event_data(matter)

    context = {
        "app": "matters",
        "subapp": "events",
        "matter": matter,
    }

    context = context | event_data

    return render(request, "matters/events/list.html", context)
