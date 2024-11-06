from datetime import date, datetime

import markdown
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404, redirect, render

from apps.contacts.models import Contact
from apps.intakes.filter_intakes import IntakeFilter
from apps.intakes.forms import IntakeForm, NoteForm
from apps.intakes.intakes import get_table_data
from apps.intakes.models import Intake, Note
from config.helpers import format_phone


@login_required
def index(request):
    request.session["intakes-view"] = "list"

    table_data = get_table_data(request)

    context = table_data
    context["app"] = "intakes"

    return render(request, "intakes/list-table.html", context)


@login_required
def intake_filter(request):
    def get_filter(request):
        filter_data = request.session.get("intake_filter", request.POST)

        return IntakeFilter(filter_data, queryset=Intake.objects.all())

    if request.method == "POST":
        request.session["intake_filter"] = request.POST

        return redirect("intakes:list")
    else:
        filter = get_filter(request)

        return render(request, "intakes/intake-filter.html", {"filter": filter})


@login_required
def quick_filter_status(request, status):
    filter_data = request.session.get("intake_filter", {})

    filter_data["status"] = status

    request.session["intake_filter"] = filter_data

    return redirect("intakes:list")


@login_required
def quick_filter_all(request):
    filter_data = {}
    filter_data["order_by"] = "-date"
    request.session["intake_filter"] = filter_data
    return redirect("intakes:list")


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

    return redirect("intakes:list")


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
        "app": "intakes",
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
        form = IntakeForm(request.POST, instance=intake)
        if form.is_valid():
            intake = form.save(commit=False)
            intake.phone = format_phone(intake.phone)
            intake.save()
            return redirect(f"/intakes/{intake.id}")

    else:
        form = IntakeForm(instance=intake)

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
        form = NoteForm(request.POST, instance=note)
        if form.is_valid():
            note = form.save(commit=False)
            note.save()
        return redirect(f"/intakes/{intake.id}")

    else:
        form = NoteForm(instance=note)

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
def delete_note(request, id):
    note = get_object_or_404(Note, pk=id)
    intake = get_object_or_404(Intake, pk=note.intake.id)
    note.delete()
    return redirect(f"/intakes/{intake.id}")


@login_required
def intake_edit_status(_, pk, status):
    intake = get_object_or_404(Intake, pk=pk)

    intake.status = status
    intake.save()

    return redirect("intakes:list")
