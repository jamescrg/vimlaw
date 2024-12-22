from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding
from apps.matters.settlement.forms import SettlementEntryForm
from apps.matters.settlement.models import SettlementEntry


@login_required
def settlement_index(request, id):
    matter = get_object_or_404(Matter, pk=id)

    proceeding = Proceeding.objects.filter(matter=matter.id, primary=True).first()
    entries = SettlementEntry.objects.filter(matter=matter.id).order_by("date")

    context = {
        "app": "matters",
        "subapp": "settlement",
        "matter": matter,
        "proceeding": proceeding,
        "entries": entries,
    }

    return render(request, "matters/settlement/main.html", context)


@login_required
def settlement_list(request, id):
    matter = get_object_or_404(Matter, pk=id)

    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()
    entries = SettlementEntry.objects.filter(matter=matter.id).order_by("date")

    context = {
        "app": "matters",
        "subapp": "settlement",
        "matter": matter,
        "proceeding": proceeding,
        "entries": entries,
    }

    return render(request, "matters/settlement/list.html", context)


@login_required
def add(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = SettlementEntryForm(request.POST, use_required_attribute=False)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.user_id = request.user.id
            entry.matter = matter
            entry.save()

            return HttpResponse(
                status=204, headers={"HX-Trigger": "matterSettlementChanged"}
            )

    # if no post data has been submitted, show the entry form
    else:
        today = date.today().strftime("%Y-%m-%d")
        form = SettlementEntryForm(
            initial={"date": today}, use_required_attribute=False
        )

    context = {
        "app": "matters",
        "subapp": "settlement",
        "matter": matter,
        "proceeding": proceeding,
        "edit": False,
        "add": True,
        "action": f"/matters/{id}/settlement/add",
        "form": form,
    }

    return render(request, "matters/settlement/form.html", context)


@login_required
def edit(request, id, entry_id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()
    entry = get_object_or_404(SettlementEntry, pk=entry_id)

    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = SettlementEntryForm(
            request.POST, instance=entry, use_required_attribute=False
        )
        if form.is_valid():
            entry = form.save(commit=False)
            entry.user_id = request.user.id
            entry.matter = matter
            entry.save()

            return HttpResponse(
                status=204, headers={"HX-Trigger": "matterSettlementChanged"}
            )

    # if no post data has been submitted, show the entry form
    else:
        form = SettlementEntryForm(instance=entry, use_required_attribute=False)

    context = {
        "app": "matters",
        "subapp": "settlement",
        "matter": matter,
        "proceeding": proceeding,
        "entry": entry,
        "edit": True,
        "add": False,
        "action": f"/matters/{id}/settlement/{entry_id}/edit",
        "form": form,
    }

    return render(request, "matters/settlement/form.html", context)


@login_required
def delete(request, matter_id, entry_id):
    entry = get_object_or_404(SettlementEntry, pk=entry_id)
    entry.delete()

    return HttpResponse(status=204, headers={"HX-Trigger": "matterSettlementChanged"})
