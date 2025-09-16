from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.agenda.events.models import Event
from apps.contacts.functions.load_contacts import load_contacts
from apps.contacts.models import Contact
from apps.matters.filter import MatterFilter
from apps.matters.forms import MatterForm
from apps.matters.get_matter_list import get_matter_list
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding
from apps.matters.settlement.models import SettlementEntry
from apps.matters.timeline.models import Fact


@login_required
def matter_index(request):
    request.session["matters-view"] = "list"

    list_data = get_matter_list(request)

    context = {
        "app": "matters",
    } | list_data

    return render(request, "matters/main.html", context)


@login_required
def matter_list(request):
    request.session["matters-view"] = "list"

    list_data = get_matter_list(request)
    context = {
        "app": "matters",
    }

    context = context | list_data

    return render(request, "matters/list.html", context)


@login_required
def filter(request):
    def get_filter(request):
        filter_data = request.session.get("matter_filter", request.POST)
        return MatterFilter(filter_data, queryset=Matter.objects.all())

    if request.method == "POST":
        filter_data = {}
        for key, val in request.POST.items():
            filter_data[key] = val
        filter_data["filter_label"] = "custom"
        request.session["matter_filter"] = filter_data
        return HttpResponse(status=204, headers={"HX-Trigger": "mattersChanged"})

    else:
        filter = get_filter(request)
        return render(request, "matters/filter.html", {"filter": filter})


@login_required
def filter_quick(request, quick_filter):
    quick_filters = {
        "open": {
            "status": "Open",
            "practice_area": "",
            "date_start": "",
            "date_end": "",
            "order_by": "name",
            "filter_label": "open",
        },
    }

    filter_data = {}
    for key, val in quick_filters[quick_filter].items():
        filter_data[key] = val

    request.session["matter_filter"] = filter_data
    request.session.modified = True

    return HttpResponse(status=204, headers={"HX-Trigger": "mattersChanged"})


@login_required
def filter_quick_status(request, status):
    filter_data = request.session.get("matter_filter", {})
    filter_data["status"] = status
    filter_data["filter_label"] = status
    request.session["matter_filter"] = filter_data
    return HttpResponse(status=204, headers={"HX-Trigger": "mattersChanged"})


@login_required
def order_by(request, order):
    filter_data = request.session.get("matter_filter", {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["matter_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "mattersChanged"})


@login_required
def detail(request, id):
    request.session["matters-view"] = "detail"
    return redirect(f"/matters/{id}/timeline")


@login_required
def add(request):
    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = MatterForm(request.POST, use_required_attribute=False)
        if form.is_valid():
            matter = form.save(commit=False)
            matter.user_id = request.user.id
            matter.save()

            return redirect("/matters")

    # if no post data has been submitted, show the matter form
    else:
        today = date.today().strftime("%Y-%m-%d")
        form = MatterForm(initial={"date_start": today}, use_required_attribute=False)
        client_list = Contact.objects.filter(client_status="Current").order_by("name")
        form.fields["client"].queryset = client_list

    context = {
        "app": "matters",
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
            print(form.errors)

    else:
        form = MatterForm(instance=matter)
        client_list = Contact.objects.filter(client_status="Current").order_by("name")

        if matter.client:
            client_list |= Contact.objects.filter(pk=matter.client.pk)

        form.fields["client"].queryset = client_list

    context = {
        "app": "matters",
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

    connected_documents = matter.documents.all()

    if request.method == "GET":
        context = {
            "matter": matter,
            "connected_documents": connected_documents,
            "has_documents": connected_documents.exists(),
        }

        return render(request, "matters/delete_confirmation.html", context)

    elif request.method == "DELETE":
        matter.delete()

        return HttpResponse(status=204, headers={"HX-Redirect": "/matters"})


@login_required
def edit_work_status(request, matter_id):
    matter = get_object_or_404(Matter, pk=matter_id)
    context = {"matter": matter}
    return render(request, "matters/edit-work-status.html", context)


@login_required
def update_work_status(request, id):
    matter = get_object_or_404(Matter, pk=id)
    matter.work_status = request.POST.get("work_status")
    matter.save()

    if request.session.get("matters-view"):
        if request.session["matters-view"] == "detail":
            return redirect(f"/matters/{matter.id}")
        if request.session["matters-view"] == "list":
            return render(request, "matters/row.html", {"matter": matter})
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
