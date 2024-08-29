from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.matters.forms import FactForm
from apps.matters.models import Fact, Matter
from apps.matters.proceedings.models import Proceeding


@login_required
def index(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()
    facts = Fact.objects.filter(matter=matter.id).order_by("date")

    context = {
        "page": "matters",
        "submodule": "timeline",
        "matter": matter,
        "proceeding": proceeding,
        "facts": facts,
    }

    return render(request, "matters/timeline/list.html", context)


@login_required
def add(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = FactForm(request.POST)
        if form.is_valid():
            fact = form.save(commit=False)
            fact.user_id = request.user.id
            fact.matter = matter
            fact.save()
            return redirect(f"/matters/{id}/timeline")

    # if no post data has been submitted, show the fact form
    else:
        today = date.today().strftime("%Y-%m-%d")
        form = FactForm(initial={"date_filed": today})

    context = {
        "page": "matters",
        "submodule": "timeline",
        "matter": matter,
        "proceeding": proceeding,
        "edit": False,
        "add": True,
        "action": f"/matters/{id}/timeline/add",
        "form": form,
    }

    return render(request, "matters/timeline/form.html", context)


@login_required
def edit(request, id, fact_id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()
    fact = get_object_or_404(Fact, pk=fact_id)

    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = FactForm(request.POST, instance=fact)
        if form.is_valid():
            fact = form.save(commit=False)
            fact.user_id = request.user.id
            fact.matter = matter
            fact.save()
            return redirect(f"/matters/{id}/timeline")

    # if no post data has been submitted, show the fact form
    else:
        form = FactForm(instance=fact)

    context = {
        "page": "matters",
        "submodule": "timeline",
        "matter": matter,
        "proceeding": proceeding,
        "fact": fact,
        "edit": True,
        "add": False,
        "action": f"/matters/{id}/timeline/{fact_id}/edit",
        "form": form,
    }

    return render(request, "matters/timeline/form.html", context)


@login_required
def delete(request, matter_id, fact_id):
    fact = get_object_or_404(Fact, pk=fact_id)
    fact.delete()
    return redirect(f"/matters/{matter_id}/timeline")


@login_required
def print(request, id):
    matter = get_object_or_404(Matter, pk=id)
    facts = Fact.objects.filter(matter=matter.id).order_by("date")

    context = {
        "matter": matter,
        "facts": facts,
    }
    return render(request, "matters/timeline/print.html", context)
