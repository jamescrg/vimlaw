from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.matters.events.get_event_data import get_event_data
from apps.matters.models import Matter


@login_required
def events_index(request, id):
    matter = get_object_or_404(Matter, pk=id)

    event_data = get_event_data(request, matter)

    context = {
        "app": "matters",
        "subapp": "events",
        "matter": matter,
    } | event_data

    return render(request, "matters/events/main.html", context)


@login_required
def events_list(request, id):
    matter = get_object_or_404(Matter, pk=id)

    event_data = get_event_data(request, matter)

    context = {
        "app": "matters",
        "subapp": "events",
        "matter": matter,
    }

    context = context | event_data

    return render(request, "matters/events/list.html", context)


@login_required
def events_filter_status(request, id, status):
    matter = get_object_or_404(Matter, pk=id)
    session_key = f"matter_events_filter_{matter.id}"
    request.session[session_key] = status if status else ""
    request.session.modified = True

    return HttpResponse(status=204, headers={"HX-Trigger": "matterEventChanged"})


@login_required
def events_filter_sort(request, id, order):
    matter = get_object_or_404(Matter, pk=id)
    session_key = f"matter_events_sort_{matter.id}"

    current_order = request.session.get(session_key, "date")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    request.session[session_key] = new_order
    request.session.modified = True

    return HttpResponse(status=204, headers={"HX-Trigger": "matterEventChanged"})
