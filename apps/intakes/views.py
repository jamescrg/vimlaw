from datetime import date, datetime

import markdown
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.contacts.models import Contact
from apps.intakes.filter_intakes import IntakeFilter
from apps.intakes.forms import IntakeForm, NoteForm
from apps.intakes.intakes import get_table_data
from apps.intakes.models import Intake, Note, UserIntakeView


@login_required
def intakes_index(request):
    request.session["intakes-view"] = "list"

    table_data = get_table_data(request)

    context = {
        "app": "intakes",
    } | table_data

    return render(request, "intakes/main.html", context)


@login_required
def intakes_list(request):
    request.session["intakes-view"] = "list"

    table_data = get_table_data(request)

    context = {
        "app": "intakes",
    } | table_data

    return render(request, "intakes/list-table.html", context)


@login_required
def intake_filter(request):
    def get_filter(request):
        filter_data = request.session.get("intake_filter", request.POST)

        return IntakeFilter(filter_data, queryset=Intake.objects.all())

    if request.method == "POST":
        request.session["intake_filter"] = request.POST

        return HttpResponse(status=204, headers={"HX-Trigger": "intakesChanged"})

    else:
        filter = get_filter(request)

        return render(request, "intakes/intake-filter.html", {"filter": filter})


@login_required
def quick_filter_status(request, status):
    filter_data = request.session.get("intake_filter", {})
    filter_data["status"] = status
    filter_data["filter_label"] = status
    request.session["intake_filter"] = filter_data
    return HttpResponse(status=204, headers={"HX-Trigger": "intakesChanged"})


@login_required
def quick_filter_all(request):
    filter_data = {}
    filter_data["order_by"] = "-date"
    filter_data["filter_label"] = "all"
    request.session["intake_filter"] = filter_data
    return HttpResponse(status=204, headers={"HX-Trigger": "intakesChanged"})


@login_required
def order_by(request, order):
    filter_data = request.session.get("intake_filter", {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["intake_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "intakesChanged"})


@login_required
def detail_index(request, id):
    request.session["intakes-view"] = "detail"

    # get the intake
    intake = get_object_or_404(Intake, pk=id)

    # Track view for badge notification system (only for open intakes)
    if intake.status == "Open":
        UserIntakeView.objects.update_or_create(
            user=request.user,
            intake=intake,
            # last_viewed_at auto-updates with auto_now=True
        )

    notes = Note.objects.filter(intake=intake).order_by("-date", "-time")
    for note in notes:
        note.details = markdown.markdown(note.details)

    # check whether the intake has been added to contacts
    try:
        contact = Contact.objects.filter(intake=intake).get()
    except ObjectDoesNotExist:
        contact = None

    context = {
        "app": "intakes",
        "intake": intake,
        "notes": notes,
        "contact": contact,
    }

    return render(request, "intakes/detail-index.html", context)


@login_required
def detail(request, id):
    request.session["intakes-view"] = "detail"

    # get the intake
    intake = get_object_or_404(Intake, pk=id)

    notes = Note.objects.filter(intake=intake).order_by("-date", "-time")
    for note in notes:
        note.details = markdown.markdown(note.details)

    # check whether the intake has been added to contacts
    try:
        contact = Contact.objects.filter(intake=intake).get()
    except ObjectDoesNotExist:
        contact = None

    context = {
        "app": "intakes",
        "intake": intake,
        "notes": notes,
        "contact": contact,
    }
    return render(request, "intakes/detail.html", context)


@login_required
def add(request):
    if request.method == "POST":
        form = IntakeForm(request.POST, use_required_attribute=False)

        if form.is_valid():
            intake = form.save(commit=False)
            intake.user_id = request.user.id
            intake.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "intakesChanged"})

    else:
        today = date.today().strftime("%Y-%m-%d")
        form = IntakeForm(initial={"date": today}, use_required_attribute=False)

    context = {
        "app": "intakes",
        "edit": False,
        "add": True,
        "action": "/intakes/add",
        "form": form,
    }

    return render(request, "intakes/form.html", context)


@login_required
def edit(request, id):
    intake = get_object_or_404(Intake, pk=id)

    if request.method == "POST":
        form = IntakeForm(request.POST, instance=intake, use_required_attribute=False)
        if form.is_valid():
            intake = form.save(commit=False)
            intake.save()
            return HttpResponse(
                status=204, headers={"HX-Trigger": "intakeDetailChanged"}
            )

    else:
        form = IntakeForm(instance=intake, use_required_attribute=False)

    context = {
        "app": "intakes",
        "edit": True,
        "add": False,
        "action": f"/intakes/{id}/edit",
        "intake": intake,
        "form": form,
    }

    return render(request, "intakes/form.html", context)


@login_required
def delete(request, id):
    intake = get_object_or_404(Intake, pk=id)
    intake.delete()
    return redirect("/intakes")


@login_required
def add_note(request, id):
    intake = get_object_or_404(Intake, pk=id)

    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = NoteForm(request.POST, use_required_attribute=False)
        if form.is_valid():
            note = form.save(commit=False)
            note.intake = intake
            note.user = request.user
            note.save()

            return HttpResponse(
                status=204, headers={"HX-Trigger": "intakeDetailChanged"}
            )

    # if no post data has been submitted, show the intake form
    else:
        today = date.today().strftime("%Y-%m-%d")
        now = datetime.now().time()
        form = NoteForm(
            initial={"date": today, "time": now}, use_required_attribute=False
        )

    context = {
        "app": "intakes",
        "edit": False,
        "add": True,
        "action": f"/intakes/{intake.id}/add-note",
        "intake": intake,
        "form": form,
    }

    return render(request, "intakes/form_note.html", context)


@login_required
def edit_note(request, id):
    note = get_object_or_404(Note, pk=id)
    intake = get_object_or_404(Intake, pk=note.intake.id)

    if request.method == "POST":
        form = NoteForm(request.POST, instance=note, use_required_attribute=False)
        if form.is_valid():
            note = form.save(commit=False)
            note.save()

            return HttpResponse(
                status=204, headers={"HX-Trigger": "intakeDetailChanged"}
            )

    else:
        form = NoteForm(instance=note, use_required_attribute=False)

    context = {
        "app": "intakes",
        "edit": True,
        "add": False,
        "action": f"/intakes/{id}/edit-note",
        "intake": intake,
        "note": note,
        "form": form,
    }

    return render(request, "intakes/form_note.html", context)


@login_required
def delete_note(_, id):
    Note.objects.filter(pk=id).delete()

    return HttpResponse(status=204, headers={"HX-Trigger": "intakeDetailChanged"})


@login_required
def intake_edit_status(request, pk, status):
    intake = get_object_or_404(Intake, pk=pk)

    intake.status = status
    intake.save()

    context = {"intake": intake}

    return render(request, "intakes/intake-status.html", context)


@login_required
def intake_edit_practice_area(request, pk, practice_area):
    intake = get_object_or_404(Intake, pk=pk)

    intake.practice_area = practice_area
    intake.save()

    context = {"intake": intake}

    return render(request, "intakes/intake-practice-area.html", context)


@login_required
def value_edit(request, pk):
    intake = get_object_or_404(Intake, pk=pk)
    context = {"intake": intake}
    return render(request, "intakes/value-edit.html", context)


@login_required
def value_update(request, pk):
    intake = get_object_or_404(Intake, pk=pk)
    value = request.POST.get("value", "")
    intake.value = int(value) if value else None
    intake.save()
    context = {"intake": intake}
    return render(request, "intakes/value-display.html", context)


@login_required
def value_display(request, pk):
    intake = get_object_or_404(Intake, pk=pk)
    context = {"intake": intake}
    return render(request, "intakes/value-display.html", context)
