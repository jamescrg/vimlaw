import json
from datetime import date, datetime, timedelta

from dateutil import parser
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

import apps.agenda.events.google as google
from apps.agenda.events.filter import EventFilter
from apps.agenda.events.forms import EventForm
from apps.agenda.events.models import Event
from apps.management.filter_manager import FilterManager
from apps.matters.models import Matter

from .events import get_table_data


@login_required
def events_index(request):
    request.session["agenda_last_tab"] = "events"
    today = date.today()
    third_day = today + timedelta(days=3)

    view_mode = request.session.get("events_view_mode", "list")
    table_data = get_table_data(request)

    events_filter = request.session.get("events_filter", {})
    events_filter_status = events_filter.get("status", "")

    context = {
        "app": "agenda",
        "subapp": "events",
        "third_day": third_day,
        "view_mode": view_mode,
        "events_filter_status": events_filter_status,
    } | table_data

    return render(request, "agenda/events/main.html", context)


@login_required
def events_list(request):
    """Returns the appropriate view (list or calendar) based on session."""
    from apps.accounts.models import CustomUser

    today = date.today()
    third_day = today + timedelta(days=3)

    view_mode = request.session.get("events_view_mode", "list")
    events_filter = request.session.get("events_filter", {})
    events_filter_status = events_filter.get("status", "")

    # Get assigned_to filter display value
    assigned_to_value = events_filter.get("assigned_to", "")
    if assigned_to_value == "unassigned":
        events_filter_assigned = "Firm"
    elif assigned_to_value:
        try:
            user = CustomUser.objects.get(pk=int(assigned_to_value))
            events_filter_assigned = user.get_short_name() or user.username
        except (ValueError, CustomUser.DoesNotExist):
            events_filter_assigned = ""
    else:
        events_filter_assigned = ""

    context = {
        "app": "agenda",
        "subapp": "events",
        "third_day": third_day,
        "view_mode": view_mode,
        "events_filter_status": events_filter_status,
        "events_filter_assigned": events_filter_assigned,
        "events_filter_assigned_value": assigned_to_value,
        "users": CustomUser.objects.filter(is_active=True).order_by(
            "first_name", "last_name"
        ),
    }

    if view_mode == "calendar":
        return render(request, "agenda/events/calendar.html", context)

    context = context | get_table_data(request)
    return render(request, "agenda/events/list.html", context)


@login_required
def events_select(request):
    return redirect("agenda:events-index")


@login_required
def events_filter(request):
    filter_manager = FilterManager(request, EventFilter, "events_filter")

    if filter_manager.process_filter():
        return HttpResponse(status=204, headers={"HX-Trigger": "eventsChanged"})

    return render(
        request,
        "agenda/events/filter.html",
        {"filter": filter_manager.get_filter(Event.objects.all())},
    )


@login_required
def events_filter_quick(request, quick_filter):
    filter_manager = FilterManager(request, EventFilter, "events_filter")
    filter_manager.apply_quick_filter(quick_filter)

    return HttpResponse(status=204, headers={"HX-Trigger": "eventsChanged"})


@login_required
def events_filter_status(request, status):
    events_filter = request.session.get("events_filter", {})
    events_filter["status"] = status if status else ""
    request.session["events_filter"] = events_filter
    request.session.modified = True

    response = render(
        request,
        "agenda/events/status-dropdown.html",
        {"events_filter_status": status},
    )
    response["HX-Trigger"] = "eventsChanged"
    return response


@login_required
def events_filter_assigned(request, assigned):
    """Filter events by assigned_to value."""
    from apps.accounts.models import CustomUser

    events_filter = request.session.get("events_filter", {})
    events_filter["assigned_to"] = assigned if assigned else ""
    request.session["events_filter"] = events_filter
    request.session.modified = True

    # Get display value for the dropdown
    if assigned == "unassigned":
        display_value = "Firm"
    elif assigned:
        try:
            user = CustomUser.objects.get(pk=int(assigned))
            display_value = user.get_short_name() or user.username
        except (ValueError, CustomUser.DoesNotExist):
            display_value = ""
    else:
        display_value = ""

    response = render(
        request,
        "agenda/events/assigned-dropdown.html",
        {
            "events_filter_assigned": display_value,
            "events_filter_assigned_value": assigned,
            "users": CustomUser.objects.filter(is_active=True).order_by(
                "first_name", "last_name"
            ),
        },
    )
    response["HX-Trigger"] = "eventsChanged"
    return response


@login_required
def events_filter_sort(request, order):
    filter_data = request.session.get("events_filter", {})

    current_order = filter_data.get("order_by", "")
    if isinstance(current_order, list):
        current_order = current_order[0] if current_order else ""

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["events_filter"] = filter_data
    request.session.modified = True

    return HttpResponse(status=204, headers={"HX-Trigger": "eventsChanged"})


@login_required
def events_add(request, matter_id=None, origin="events"):
    # identify the origin of the request (events or agenda)
    if request.method == "GET":
        request.session["origin"] = origin
        request.session.modified = True

    # set the origin of the request, defaulting to "events"
    origin = request.session.get("origin", "events")

    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = EventForm(request.POST, use_required_attribute=False)
        if form.is_valid():
            # initialize event data
            event = form.save(commit=False)
            event.user = request.user

            # Auto-set end_time to 1 hour after start_time if only start_time provided
            if event.start_time and not event.end_time:
                start_datetime = datetime.combine(date.today(), event.start_time)
                end_datetime = start_datetime + timedelta(hours=1)
                event.end_time = end_datetime.time()

            # add to google account
            # check for test user
            if request.user.username != "Ollie":
                if google.check_credentials():
                    event.google_id = google.add_event(event)

            # save event to database with google id
            event.save()

            if origin == "matters":
                return HttpResponse(
                    status=204, headers={"HX-Trigger": "matterEventChanged"}
                )
            else:
                return HttpResponse(status=204, headers={"HX-Trigger": "eventsChanged"})

    # if no post data has been submitted, show the contact form
    else:
        # Use date from query param if provided, otherwise today
        date_param = request.GET.get("date")
        if date_param:
            try:
                initial_date = datetime.strptime(date_param, "%Y-%m-%d").date()
            except ValueError:
                initial_date = date.today()
        else:
            initial_date = date.today()

        if matter_id:
            form = EventForm(
                initial={
                    "matter": matter_id,
                    "date": initial_date,
                },
                use_required_attribute=False,
            )
        else:
            form = EventForm(
                initial={
                    "date": initial_date,
                },
                use_required_attribute=False,
            )

    form.fields["matter"].queryset = Matter.objects.filter(
        status__in=["Pending", "Open"]
    ).order_by("name")

    google_connected = google.check_credentials()

    today = date.today().strftime("%Y-%m-%d")

    context = {
        "app": "agenda",
        "subapp": "events",
        "today": today,
        "edit": False,
        "add": True,
        "results": None,
        "action": "/events/add",
        "google_connected": google_connected,
        "form": form,
    }

    return render(request, "agenda/events/form.html", context)


@login_required
def events_edit(request, id, origin="events"):
    # identify the origin of the request (events or agenda)
    if request.method == "GET":
        request.session["origin"] = origin
    origin = request.session.get("origin", "events")

    event = get_object_or_404(Event, pk=id)

    if request.method == "POST":
        form = EventForm(request.POST, instance=event, use_required_attribute=False)

        # get list of open matters
        matter_list = Matter.objects.filter(status__in=["Pending", "Open"]).order_by(
            "name"
        )

        # make sure the matter associated with the event is in the list
        # if not, add it
        # this ensures the matter is available in the form select element
        # even when the matter is closed
        if event.matter and event.matter not in matter_list:
            matter_list |= Matter.objects.filter(pk=event.matter.id)

        # bind list of matters to select element
        form.fields["matter"].queryset = matter_list

        if form.is_valid():
            event = form.save(commit=False)
            event.user = request.user

            # Auto-set end_time to 1 hour after start_time if only start_time provided
            if event.start_time and not event.end_time:
                start_datetime = datetime.combine(date.today(), event.start_time)
                end_datetime = start_datetime + timedelta(hours=1)
                event.end_time = end_datetime.time()

            if google.check_credentials() and event.google_id:
                google.edit_event(event)

            event.save()

            if origin == "matters":
                return HttpResponse(
                    status=204, headers={"HX-Trigger": "matterEventChanged"}
                )
            else:
                return HttpResponse(status=204, headers={"HX-Trigger": "eventsChanged"})

    else:
        form = EventForm(
            instance=event,
            initial={"matter": event.matter},
            use_required_attribute=False,
        )

    # pull the list of matters
    matter_list = Matter.objects.filter(status__in=["Pending", "Open"]).order_by("name")

    # make sure the matter associated with the event is in the list
    # if not, add it
    # this ensures the matter is available in the form select element
    # even when the matter is closed
    if event.matter and event.matter not in matter_list:
        matter_list |= Matter.objects.filter(pk=event.matter.id)

    # bind list of matters to select element
    form.fields["matter"].queryset = matter_list

    google_connected = google.check_credentials()

    context = {
        "app": "events",
        "edit": True,
        "add": False,
        "results": None,
        "action": f"/events/{id}/edit",
        "event": event,
        "google_connected": google_connected,
        "form": form,
        "origin": origin,
    }

    return render(request, "agenda/events/form.html", context)


@login_required
def events_delete(request, id, origin="events"):
    # identify the origin of the request (events or agenda)
    if request.method == "GET":
        request.session["origin"] = origin
    origin = request.session.get("origin", "events")

    event = get_object_or_404(Event, pk=id)

    if google.check_credentials() and event.google_id:
        google.delete_event(event)

    event.delete()

    if origin == "matters":
        return HttpResponse(status=204, headers={"HX-Trigger": "matterEventChanged"})
    else:
        return HttpResponse(status=204, headers={"HX-Trigger": "eventsChanged"})


@login_required
def events_google_sync(request, id):
    event = get_object_or_404(Event, pk=id)
    event.google_id = google.add_event(event)
    event.save()
    return redirect("/events")


@login_required
def events_deadline_results(request, matter_id=None):
    # get the submitted initial date and days
    initial_date = request.POST["initial_date"]
    days = int(request.POST["days"])

    # convert initial date to python date object
    initial_date = parser.parse(initial_date)

    # calculate deadline
    deadline = initial_date + timedelta(days=days)

    # determine whether deadline falls on a weekday
    # if so, provide the date of the next Monday
    deadline_weekday = deadline.strftime("%A")
    next_workday = None
    if deadline_weekday == "Saturday":
        next_workday = deadline + timedelta(days=2)
    if deadline_weekday == "Sunday":
        next_workday = deadline + timedelta(days=1)

    # store the ddeadline results in the calc dictionary
    results = {}
    results["initial_date"] = initial_date
    results["days"] = days
    results["deadline"] = deadline
    results["deadline_weekday"] = deadline_weekday
    results["next_workday"] = next_workday

    context = {
        "results": results,
    }

    return render(request, "agenda/events/deadline-calculator-results.html", context)


@login_required
def events_deadline_form(request):
    today = date.today()
    today = today.strftime("%Y-%m-%d")
    context = {
        "today": today,
    }
    return render(request, "agenda/events/deadline-calculator-form.html", context)


@login_required
def events_deadline_modal(request):
    today = date.today().strftime("%Y-%m-%d")
    context = {"today": today}
    return render(request, "agenda/events/deadline-calculator-modal.html", context)


@login_required
def events_calendar(request):
    """Render the calendar view partial."""
    request.session["agenda_last_tab"] = "events"
    today = date.today()
    third_day = today + timedelta(days=3)

    events_filter = request.session.get("events_filter", {})
    events_filter_status = events_filter.get("status", "")

    context = {
        "app": "agenda",
        "subapp": "events",
        "third_day": third_day,
        "view_mode": "calendar",
        "events_filter_status": events_filter_status,
    }
    return render(request, "agenda/events/calendar.html", context)


@login_required
def events_api(request):
    """
    JSON API for FullCalendar event feed.
    Exception to HTMX HTML-only rule: calendar requires JSON.
    """
    start_param = request.GET.get("start")
    end_param = request.GET.get("end")

    # Parse FullCalendar's ISO date parameters
    if start_param:
        start_date = datetime.fromisoformat(start_param.replace("Z", "+00:00")).date()
    else:
        start_date = date.today() - timedelta(days=30)

    if end_param:
        end_date = datetime.fromisoformat(end_param.replace("Z", "+00:00")).date()
    else:
        end_date = date.today() + timedelta(days=60)

    # Apply existing filter from session
    events_filter_data = request.session.get("events_filter", {})
    filter_instance = EventFilter(events_filter_data, queryset=Event.objects.all())
    events = filter_instance.qs.filter(date__gte=start_date, date__lte=end_date)

    # Convert to FullCalendar format
    calendar_events = []
    for event in events:
        matter_name = event.matter.name if event.matter else ""
        description = event.description or "Untitled"

        # Build title: {Matter} - {Description} - {User Initials}
        title_parts = []
        if matter_name:
            title_parts.append(matter_name)
        title_parts.append(description)
        if event.assigned_to and event.assigned_to.initials:
            title_parts.append(event.assigned_to.initials)
        title = " - ".join(title_parts)

        fc_event = {
            "id": str(event.id),
            "title": title,
            "extendedProps": {
                "matter": event.matter.name if event.matter else "",
                "matter_id": event.matter.id if event.matter else None,
                "location": event.location or "",
                "party": event.party or "",
                "status": event.status or "",
            },
        }

        # Handle timed vs all-day events
        if event.start_time and event.end_time:
            fc_event["start"] = f"{event.date}T{event.start_time}"
            fc_event["end"] = f"{event.date}T{event.end_time}"
            fc_event["allDay"] = False
        elif event.start_time:
            fc_event["start"] = f"{event.date}T{event.start_time}"
            fc_event["allDay"] = False
        else:
            fc_event["start"] = str(event.date)
            fc_event["allDay"] = True

        # Add status-based styling
        if event.status == "Pending":
            fc_event["className"] = "fc-event-pending"
        elif event.status == "Complete":
            fc_event["className"] = "fc-event-complete"
        elif event.status == "Missed":
            fc_event["className"] = "fc-event-missed"

        calendar_events.append(fc_event)

    return JsonResponse(calendar_events, safe=False)


@login_required
@require_POST
def events_quick_update(request, id):
    """
    Quick update for drag-drop operations.
    Only updates date/time fields.
    """
    event = get_object_or_404(Event, pk=id)

    # Parse the update data
    data = json.loads(request.body)

    if "date" in data:
        event.date = datetime.strptime(data["date"], "%Y-%m-%d").date()

    if "start_time" in data:
        if data["start_time"]:
            event.start_time = datetime.strptime(data["start_time"], "%H:%M:%S").time()
        else:
            event.start_time = None

    if "end_time" in data:
        if data["end_time"]:
            event.end_time = datetime.strptime(data["end_time"], "%H:%M:%S").time()
        else:
            event.end_time = None

    event.save()

    # Sync to Google Calendar
    if google.check_credentials() and event.google_id:
        google.edit_event(event)

    return HttpResponse(status=204, headers={"HX-Trigger": "eventsChanged"})


@login_required
@require_POST
def events_view_mode(request, mode):
    """Toggle between list and calendar view modes."""
    request.session["events_view_mode"] = mode
    request.session.modified = True
    return HttpResponse(status=204, headers={"HX-Trigger": "eventsViewChanged"})
