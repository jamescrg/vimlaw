from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.agenda.tasks.tasks import get_table_data
from apps.events.models import Event


@login_required
def index(request):
    page = "agenda"

    tab = request.session.get("agenda_tab", "tasks")
    # check whether events have been hidden
    show_events = request.session.get("show_events", True)

    # if events are hidden, check the date they were hidden
    # if that date is less than today, show them
    if not show_events:
        today = date.today()
        timestamp = int(request.session.get("hide_expire"))
        old_date = date.fromtimestamp(timestamp)
        if today > old_date:
            show_events = True
            request.session["show_events"] = True

    # if events are shown, load them
    if show_events:
        today = date.today()
        three_weeks_out = today + timedelta(days=21)
        three_days_out = today + timedelta(days=3)
        events = Event.objects.filter(
            status="Pending", date__lt=three_weeks_out
        ).order_by("date")
    else:
        events = None
        three_days_out = None

    table_data = get_table_data(request)

    # save the currently selected matter in the add task form
    # so multiple tasks can quickly be added to a matter
    agenda_matter = request.session.get("agenda_matter")

    context = {
        "tab": tab,
        "page": page,
        "show_events": show_events,
        "events": events,
        "three_days_out": three_days_out,
        "agenda_matter": agenda_matter,
    }

    context = context | table_data
    return render(request, "agenda/agenda-main.html", context)


@login_required
def set_tab(request, tab):
    request.session["agenda_tab"] = tab
    request.session.modified = True

    return redirect("/agenda")
