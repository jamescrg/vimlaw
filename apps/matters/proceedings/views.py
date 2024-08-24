from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.matters.models import Matter
from apps.matters.proceedings.forms import ProceedingForm
from apps.matters.proceedings.models import Proceeding


@login_required
def index(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()
    proceedings = Proceeding.objects.filter(matter=matter.id).order_by("-id")

    context = {
        "page": "matters",
        "submodule": "proceedings",
        "matter": matter,
        "proceeding": proceeding,
        "proceedings": proceedings,
    }

    return render(request, "matters/proceedings/list.html", context)


@login_required
def add(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = ProceedingForm(request.POST)
        if form.is_valid():
            proceeding = form.save(commit=False)
            proceeding.user_id = request.user.id
            proceeding.matter = matter
            proceeding.save()
            return redirect(f"/matters/{id}/proceedings")

    # if no post data has been submitted, show the proceeding form
    else:
        today = date.today().strftime("%Y-%m-%d")
        form = ProceedingForm(initial={"date_filed": today})

    context = {
        "page": "matters",
        "submodule": "proceedings",
        "matter": matter,
        "proceeding": proceeding,
        "edit": False,
        "add": True,
        "action": f"/matters/{id}/proceedings/add",
        "form": form,
    }

    return render(request, "matters/proceedings/form.html", context)


@login_required
def edit(request, id, proceeding_id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    proceeding_for_edits = get_object_or_404(Proceeding, pk=proceeding_id)

    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = ProceedingForm(request.POST, instance=proceeding_for_edits)
        if form.is_valid():
            proceeding_for_edits = form.save(commit=False)
            proceeding_for_edits.user_id = request.user.id
            proceeding_for_edits.matter = matter
            proceeding_for_edits.save()
            return redirect(f"/matters/{id}/proceedings")

    # if no post data has been submitted, show the proceeding form
    else:
        form = ProceedingForm(instance=proceeding_for_edits)

    context = {
        "page": "matters",
        "submodule": "proceedings",
        "matter": matter,
        "proceeding": proceeding,
        "proceeding_for_edits": proceeding_for_edits,
        "edit": True,
        "add": False,
        "action": f"/matters/{id}/proceedings/{proceeding_id}/edit",
        "form": form,
    }

    return render(request, "matters/proceedings/form.html", context)


@login_required
def delete(request, matter_id, proceeding_id):
    proceeding = get_object_or_404(Proceeding, pk=proceeding_id)
    proceeding.delete()
    return redirect(f"/matters/{matter_id}/proceedings")
