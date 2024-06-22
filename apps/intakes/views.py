from datetime import date, datetime

import markdown
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render

from apps.contacts.models import Contact
from apps.intakes.filter import Filter
from apps.intakes.forms import IntakeForm, NoteForm
from apps.intakes.models import Intake, Note
from config import settings_local
from config.helpers import format_phone
from apps.intakes.intakes import get_table_data


@login_required
def index(request):
    request.session["intakes-view"] = "list"

    context = {
        "page": "intakes",
    }

    return render(request, "intakes/list.html", context)


@login_required
def list_data(request):
    table_data = get_table_data(request)
    context = table_data
    return render(request, "intakes/list-table.html", context)


@login_required
def filter(request):
    filter = Filter(request).values
    areas = [
        "General",
        "Boundary Dispute",
        "Title Dispute",
        "LLT - LL",
        "LLT - T",
        "Quiet Title",
        "HOA",
        "Home Defect",
    ]
    context = {
        "page": "intakes",
        "filter": filter,
        "areas": areas,
    }
    return render(request, "intakes/filter.html", context)


@login_required
def filter_update(request):
    filter = Filter(request)
    filter.update(request)
    return redirect("/intakes")


@login_required
def filter_quick(request, quick_filter):
    filter = Filter(request)
    filter.set_quick_filter(request, quick_filter)
    return redirect("/intakes")


@login_required
def order(request, order):
    filter = Filter(request)
    filter.order(request, order)
    return redirect("/intakes")


@login_required
def detail(request, id):
    # get the intake
    intake = get_object_or_404(Intake, pk=id)

    notes = Note.objects.filter(intake=intake).order_by("-date", "-id")
    for note in notes:
        note.details = markdown.markdown(note.details)

    # check whether the intake has been added to contacts
    try:
        contact = Contact.objects.filter(intake=intake).get()
    except ObjectDoesNotExist:
        contact = None

    context = {
        "page": "intakes",
        "intake": intake,
        "notes": notes,
        "contact": contact,
    }
    return render(request, "intakes/detail.html", context)


@login_required
def detail_data(request, id):
    intake = get_object_or_404(Intake, pk=id)
    context = {
        "intake": intake,
    }
    return render(request, "intakes/detail-table.html", context)


@login_required
def add(request):
    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = IntakeForm(request.POST)
        if form.is_valid():
            # save the intake
            intake = form.save(commit=False)
            intake.user_id = request.user.id
            intake.phone = format_phone(intake.phone)
            intake.save()

            # send alert re intake added
            # send_mail(
            #     "New Intake Added",
            #     f"""New intake added: {intake.name}
            #     {intake.phone}
            #     {intake.email}""",
            #     settings_local.SERVER_EMAIL,
            #     settings_local.TEST_EMAIL_RECIPIENT,
            #     fail_silently=False,
            # )

            return redirect("/intakes")

    # if no post data has been submitted, show the intake form
    else:
        today = date.today().strftime("%Y-%m-%d")
        form = IntakeForm(initial={"date": today})

    context = {
        "page": "intakes",
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
        form = IntakeForm(request.POST, instance=intake)
        if form.is_valid():
            intake = form.save(commit=False)
            intake.phone = format_phone(intake.phone)
            intake.save()
            return redirect("/intakes")

    else:
        form = IntakeForm(instance=intake)

    context = {
        "page": "intakes",
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
        form = NoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.intake = intake
            note.user = request.user
            note.save()
            return redirect(f"/intakes/{intake.id}")

    # if no post data has been submitted, show the intake form
    else:
        today = date.today().strftime("%Y-%m-%d")
        now = datetime.now().time()
        form = NoteForm(initial={"date": today, "time": now})

    context = {
        "page": "intakes",
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
        form = NoteForm(request.POST, instance=note)
        if form.is_valid():
            note = form.save(commit=False)
            note.save()
        return redirect(f"/intakes/{intake.id}")

    else:
        form = NoteForm(instance=note)

    context = {
        "page": "intakes",
        "edit": True,
        "add": False,
        "action": f"/intakes/{id}/edit-note",
        "intake": intake,
        "note": note,
        "form": form,
    }

    return render(request, "intakes/form_note.html", context)


@login_required
def delete_note(request, id):
    note = get_object_or_404(Note, pk=id)
    intake = get_object_or_404(Intake, pk=note.intake.id)
    note.delete()
    return redirect(f"/intakes/{intake.id}")
