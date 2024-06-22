from datetime import date, timedelta
from dateutil import parser

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.shortcuts import redirect
from django.shortcuts import get_object_or_404

from apps.matters.models import Matter
from apps.events.models import Event
from apps.events.forms import EventForm
import apps.events.google as google


@login_required
def index(request):
    today = date.today()
    third_day = today + timedelta(days=3)

    events = Event.objects.filter(status="Pending").order_by("date")

    context = {
        "page": "events",
        "events": events,
        "third_day": third_day,
    }

    return render(request, "events/list.html", context)


@login_required
def add(request, matter_id=None, origin="events"):
    # identify the origin of the request (events or agenda)
    if request.method == "GET":
        request.session["origin"] = origin

    # set the origin of the request, defaulting to "events"
    origin = request.session.get("origin", "events")

    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = EventForm(request.POST)
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
                return redirect(f"/matters/{event.matter_id}/events")
            else:
                return redirect(origin)

    # if no post data has been submitted, show the contact form
    else:
        if matter_id:
            form = EventForm(
                initial={
                    "matter": matter_id,
                    "date": date.today(),
                }
            )
        else:
            form = EventForm(
                initial={
                    "date": date.today(),
                }
            )

    form.fields["matter"].queryset = Matter.objects.filter(
            status="Open").order_by("name")

    google_connected = google.check_credentials()

    today = date.today().strftime("%Y-%m-%d")

    context = {
        "page": "events",
        "today": today,
        "edit": False,
        "add": True,
        "results": None,
        "action": "/events/add",
        "google_connected": google_connected,
        "form": form,
    }

    return render(request, "events/form.html", context)


@login_required
def edit(request, id, origin="events"):
    # identify the origin of the request (events or agenda)
    if request.method == "GET":
        request.session["origin"] = origin
    origin = request.session.get("origin", "events")

    event = get_object_or_404(Event, pk=id)

    if request.method == "POST":
        form = EventForm(request.POST, instance=event)

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
                return redirect(f"/matters/{event.matter_id}/events")
            else:
                return redirect(origin)

    else:
        form = EventForm(instance=event, initial={"matter": event.matter})

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
        "page": "events",
        "edit": True,
        "add": False,
        "results": None,
        "action": f"/events/{id}/edit",
        "event": event,
        "google_connected": google_connected,
        "form": form,
        "origin": origin,
    }

    return render(request, "events/form.html", context)


@login_required
def delete(request, id, origin="events"):
    # identify the origin of the request (events or agenda)
    if request.method == "GET":
        request.session["origin"] = origin
    origin = request.session.get("origin", "events")

    event = get_object_or_404(Event, pk=id)

    if google.check_credentials() and event.google_id:
        google.delete_event(event)

    event.delete()

    if origin == "matters":
        return redirect(f"/matters/{event.matter_id}/events")
    else:
        return redirect(origin)


@login_required
def google_sync(request, id):
    event = get_object_or_404(Event, pk=id)
    event.google_id = google.add_event(event)
    event.save()
    return redirect("/events")


@login_required
def deadline_results(request, matter_id=None):

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

    return render(request, "events/deadline-calculator-results.html", context)
