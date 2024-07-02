from datetime import date

from dateutil import parser
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

import config.appdata as appdata
from apps.contacts.models import Contact
from apps.events.models import Event
from apps.matters.filter import Filter
from apps.matters.forms import MatterForm
from apps.matters.load_contacts import load_contacts
from apps.matters.models import Fact, Matter, Proceeding, SettlementEntry


@login_required
def index(request):
    request.session["matters-view"] = "list"

    filter = Filter(request).values

    if filter["date_from"]:
        filter["date_from"] = parser.parse(filter["date_from"])

    if filter["date_to"]:
        filter["date_to"] = parser.parse(filter["date_to"])

    matters = Matter.objects.all()

    if filter["status"]:
        matters = matters.filter(status=filter["status"])
    if filter["date_from"]:
        matters = matters.filter(date_start__gt=filter["date_from"])
    if filter["date_to"]:
        matters = matters.filter(date_start__lt=filter["date_to"])
    if filter["firm"]:
        matters = matters.filter(firm=filter["firm"])
    if filter["area"]:
        matters = matters.filter(practice_area=filter["area"])
    if filter["order"] == "name":
        matters = matters.order_by("name")
    if filter["order"] == "description":
        matters = matters.order_by("description")

    number_matters = matters.count()

    context = {
        "page": "matters",
        "edit": False,
        "filter": filter,
        "matters": matters,
        "number_matters": number_matters,
    }

    return render(request, "matters/list.html", context)


@login_required
def filter(request):
    filter = Filter(request).values
    firms = appdata.firms
    areas = appdata.areas
    context = {
        "page": "matters",
        "filter": filter,
        "firms": firms,
        "areas": areas,
    }
    return render(request, "matters/filter.html", context)


@login_required
def filter_update(request):
    filter = Filter(request)
    filter.update(request)
    return redirect("/matters")


@login_required
def filter_quick(request, quick_filter):
    filter = Filter(request)
    filter.set_quick_filter(request, quick_filter)
    return redirect("/matters")


@login_required
def order(request, order):
    filter = Filter(request)
    filter.order(request, order)
    return redirect("/matters")


@login_required
def detail(request, id):
    request.session["matters-view"] = "detail"
    return redirect(f"/matters/{id}/contacts")


@login_required
def add(request):
    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = MatterForm(request.POST)
        if form.is_valid():
            matter = form.save(commit=False)
            matter.user_id = request.user.id
            matter.save()
            return redirect("/matters")

    # if no post data has been submitted, show the matter form
    else:
        today = date.today().strftime("%Y-%m-%d")
        form = MatterForm(initial={"date_start": today})
        client_list = Contact.objects.filter(client_status="Current").order_by("name")
        form.fields["client"].queryset = client_list

    context = {
        "page": "matters",
        "edit": False,
        "add": True,
        "action": "/matters/add",
        "form": form,
    }

    return render(request, "matters/form.html", context)


@login_required
def edit(request, id):
    matter = get_object_or_404(Matter, pk=id)

    if request.method == "POST":
        form = MatterForm(request.POST, instance=matter)
        if form.is_valid():
            matter = form.save(commit=False)
            matter.user_id = request.user.id
            matter.save()
            if request.session.get("matters-view"):
                if request.session["matters-view"] == "detail":
                    return redirect(f"/matters/{matter.id}")
                if request.session["matters-view"] == "list":
                    return redirect("/matters")
            else:
                return redirect("/matters")

    else:
        form = MatterForm(instance=matter)
        client_list = Contact.objects.filter(client_status="Current").order_by("name")
        form.fields["client"].queryset = client_list

    context = {
        "page": "matters",
        "edit": True,
        "add": False,
        "action": f"/matters/{id}/edit",
        "matter": matter,
        "form": form,
    }

    return render(request, "matters/form.html", context)


@login_required
def delete(request, id):
    matter = get_object_or_404(Matter, pk=id)
    matter.delete()
    return redirect("/matters")


@login_required
def edit_description(request, id):
    matter = get_object_or_404(Matter, pk=id)
    matter.description = request.POST.get("description")
    matter.save()

    if request.session.get("matters-view"):
        if request.session["matters-view"] == "detail":
            return redirect(f"/matters/{matter.id}")
        if request.session["matters-view"] == "list":
            return redirect("/matters")
    else:
        return redirect("/matters")


@login_required
def print(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()
    relationship_groups = load_contacts(matter)
    events = Event.objects.filter(matter=id).order_by("-date")
    proceedings = Proceeding.objects.filter(matter=matter.id).order_by("-id")
    entries = SettlementEntry.objects.filter(matter=matter.id).order_by("date")
    facts = Fact.objects.filter(matter=matter.id).order_by("date")

    context = {
        "matter": matter,
        "proceeding": proceeding,
        "relationship_groups": relationship_groups,
        "events": events,
        "proceedings": proceedings,
        "entries": entries,
        "facts": facts,
    }

    return render(request, "matters/print.html", context)
