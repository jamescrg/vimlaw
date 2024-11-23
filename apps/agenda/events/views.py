from datetime import date, timedelta

from dateutil import parser
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

import apps.agenda.events.google as google
from apps.agenda.events.filter import EventFilter
from apps.agenda.events.forms import EventForm
from apps.agenda.events.models import Event
from apps.management.filter_manager import FilterManager
from apps.matters.models import Matter

from .events import get_table_data


@login_required
def events_index(request):
    if google.check_credentials():
        try:
            google.remove_deleted_events()
        except Exception as err:
            print(f"Error removing: {err}")

    today = date.today()
    third_day = today + timedelta(days=3)

    table_data = get_table_data(request)

    context = {
        "app": "agenda",
        "subapp": "events",
        "third_day": third_day,
    } | table_data

    return render(request, "agenda/events/main.html", context)


@login_required
def events_list(request):
    today = date.today()
    third_day = today + timedelta(days=3)

    context = {
        "app": "agenda",
        "subapp": "events",
        "third_day": third_day,
    }

    context = context | get_table_data(request)

    return render(request, "agenda/events/list.html", context)


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
            event.user_id = request.user.id

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
        if matter_id:
            form = EventForm(
                initial={
                    "matter": matter_id,
                    "date": date.today(),
                },
                use_required_attribute=False,
            )
        else:
            form = EventForm(
                initial={
                    "date": date.today(),
                },
                use_required_attribute=False,
            )

    form.fields["matter"].queryset = Matter.objects.filter(status="Open").order_by(
        "name"
    )

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
        matter_list = Matter.objects.filter(status="Open").order_by("name")

        # make sure the matter associated with the event is in the list
        # if not, add it
        # this ensures the matter is available in the form select element
        # even when the matter is closed
        if event.matter not in matter_list:
            matter_list |= Matter.objects.filter(pk=event.matter.id)

        # bind list of matters to select element
        form.fields["matter"].queryset = matter_list

        if form.is_valid():
            event = form.save(commit=False)
            event.user_id = request.user.id

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
    matter_list = Matter.objects.filter(status="Open").order_by("name")

    # make sure the matter associated with the event is in the list
    # if not, add it
    # this ensures the matter is available in the form select element
    # even when the matter is closed
    if event.matter not in matter_list:
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
