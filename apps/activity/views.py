from datetime import date

from dateutil import parser
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404, redirect, render

import config.appdata as appdata
from apps.accounts.models import CustomUser
from apps.activity.filter import Filter
from apps.activity.forms import ExpenseEntryForm, TimeEntryForm
from apps.activity.models import ExpenseEntry, TimeEntry
from apps.activity.summary import calculate_summary
from apps.matters.models import Matter, Rate


@login_required
def index(request):
    """
    Display a list of activity entries

    Loads an instance of Filter, which holds a list of paramaters defining
    which entries to display.

    Calls the "calculate_summary" function to calculate totals of
    hours and fees.
    """

    filter = Filter(request).values

    entries = TimeEntry.objects.all()
    expense_entries = ExpenseEntry.objects.all()

    if filter["date_from"]:
        if isinstance(filter["date_from"], str):
            filter["date_from"] = parser.parse(filter["date_from"])
        entries = entries.filter(date__gte=filter["date_from"])
        expense_entries = expense_entries.filter(date__gte=filter["date_from"])

    if filter["date_to"]:
        if isinstance(filter["date_to"], str):
            filter["date_to"] = parser.parse(filter["date_to"])
        entries = entries.filter(date__lte=filter["date_to"])
        expense_entries = expense_entries.filter(date__lte=filter["date_to"])

    if filter["firm"]:
        entries = entries.filter(matter__firm=filter["firm"])
        expense_entries = expense_entries.filter(matter__firm=filter["firm"])

    if filter["matter"]:
        matter = get_object_or_404(Matter, pk=filter["matter"])
        entries = entries.filter(matter=matter)
        expense_entries = expense_entries.filter(matter=matter)

    if filter["user"] and filter["user"] != "All":
        user = get_object_or_404(CustomUser, pk=filter["user"])
        entries = entries.filter(user=user)
        expense_entries = expense_entries.filter(user=user)

    if filter["keyword"]:
        expense_entries = expense_entries.filter(
            description__icontains=filter["keyword"]
        )

    if filter["comp"]:
        if filter["comp"] == "Yes":
            entries = entries.filter(comp=1)
            expense_entries = expense_entries.filter(comp=1)
        if filter["comp"] == "No":
            entries = entries.filter(comp=0)
            expense_entries = expense_entries.filter(comp=0)

    if filter["entered"]:
        if filter["entered"] == "Yes":
            entries = entries.filter(entered=1)
            expense_entries = expense_entries.filter(entered=1)
        if filter["entered"] == "No":
            entries = entries.filter(entered=0)
            expense_entries = expense_entries.filter(entered=0)

    if filter["order"]:
        if filter["order"] == "date, ascending":
            entries = entries.order_by("date", "id")
            expense_entries = expense_entries.order_by("date", "id")
        else:
            entries = entries.order_by("-date", "-id")
            expense_entries = expense_entries.order_by("-date", "-id")

    entries = entries[:1000]
    expense_entries = expense_entries[:1000]

    number_entries = entries.count()

    summary = calculate_summary(entries, expense_entries)

    context = {
        "page": "activity",
        "edit": False,
        "filter": filter,
        "entries": entries,
        "expense_entries": expense_entries,
        "number_entries": number_entries,
        "summary": summary,
    }

    return render(request, "activity/list.html", context)


@login_required
def filter(request):
    filter = Filter(request).values
    if filter["matter"]:
        filter["matter"] = int(filter["matter"])
    if filter["user"] != "All":
        filter["user"] = int(filter["user"])
    firms = appdata.firms
    matters = Matter.objects.filter(status="Open").order_by("name")
    users = CustomUser.objects.all()
    context = {
        "page": "activity",
        "filter": filter,
        "firms": firms,
        "matters": matters,
        "users": users,
    }
    return render(request, "activity/filter.html", context)


@login_required
def filter_update(request):
    filter = Filter(request)
    filter.update(request)
    return redirect("/activity")


@login_required
def filter_quick(request, quick_filter):
    filter = Filter(request)
    filter.set_quick_filter(request, quick_filter)
    return redirect("/activity")


@login_required
def filter_matter(request, id):
    filter = Filter(request)
    filter.matter(request, id)
    return redirect("/activity")


@login_required
def add(request, id=None):
    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = TimeEntryForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.user_id = request.user.id

            codes = {
                "attn ": "attention ",
                "Attn ": "Attention ",
                "mot ": "motion ",
                "Mot ": "Motion ",
                "Aff ": "Affidavit ",
                "conf ": "conference ",
                "Conf ": "Conference ",
                "conf. ": "conference ",
                "Conf. ": "Conference ",
                " resp ": " response ",
                " Resp ": " Response ",
                " opp ": " opposition ",
                " Opp ": " Opposition ",
                " vm ": " voicemail ",
                " vm.": " voicemail.",
                "Vm ": "Voicemail ",
                " Vm.": " Left voicemail.",
                "dep ": "deposition",
                "Dep ": "Deposition",
                " OC": " opposing counsel",
                " SMF": " Statement of Material Facts",
                " SM": " Special Master",
                " MSJ": " Motion for Summary Judgment",
                " MTD": " Motion to Dismiss",
            }

            for key, val in codes.items():
                entry.actions = entry.actions.replace(key, val)

            entry.save()
            return redirect("/activity")

    # if no post data has been submitted, show the entry form
    else:
        today = date.today().strftime("%Y-%m-%d")
        if id:
            matter = get_object_or_404(Matter, pk=id)

            try:
                rate = Rate.objects.filter(matter=matter, user=request.user).get()
                rate = rate.matter_rate
            except ObjectDoesNotExist:
                rate = request.user.user_rate

            form = TimeEntryForm(
                initial={
                    "date": today,
                    "hours": 0.2,
                    "matter": matter,
                    "rate": rate,
                }
            )
        else:
            form = TimeEntryForm(initial={"date": today, "hours": 0.2})

    # get list of matters for activity form
    matter_list = Matter.objects.filter(status="Open").order_by("name")

    matter_rates = {}
    for matter in matter_list:
        try:
            rate = Rate.objects.filter(matter=matter, user=request.user).get()
            matter_rates.update({matter.id: rate.matter_rate})
        except ObjectDoesNotExist:
            matter_rates.update({matter.id: request.user.user_rate})

    # if a single matter is selected,  pull that matter as a quersyset
    if id:
        selected_matter = Matter.objects.filter(id=id)

        # if the matter is closed, add it to the matter list
        # if it is open, don't add it
        # avoid creating two instances of the same matter
        if selected_matter.first().status == "Closed":
            matter_list |= selected_matter

    # set the form fields
    form.fields["matter"].queryset = matter_list

    context = {
        "page": "activity",
        "edit": False,
        "add": True,
        "action": "/activity/add",
        "form": form,
        "matter_list": matter_list,
        "matter_rates": matter_rates,
    }

    return render(request, "activity/form.html", context)


@login_required
def add_expense(request, id=None):
    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = ExpenseEntryForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.user_id = request.user.id
            codes = {
                "ff ": "Filing fee ",
                "fx ": "FedEx ",
                "ml ": "Mail ",
            }
            for key, val in codes.items():
                entry.description = entry.description.replace(key, val)
            entry.save()
            return redirect("/activity")

    # if no post data has been submitted, show the entry form
    else:
        today = date.today().strftime("%Y-%m-%d")
        if id:
            matter = get_object_or_404(Matter, pk=id)
            form = ExpenseEntryForm(
                initial={
                    "date": today,
                    "matter": matter,
                }
            )
        else:
            form = ExpenseEntryForm(initial={"date": today})

    # get list of matters for activity form
    matter_list = Matter.objects.filter(status="Open").order_by("name")

    # if a single matter is selected,  pull that matter as a quersyset
    if id:
        selected_matter = Matter.objects.filter(id=id)

        # if the matter is closed, add it to the matter list
        # if it is open, don't add it; avoid creating two instances of the same matter
        if selected_matter.first().status == "Closed":
            matter_list |= selected_matter

    # set the form fields
    form.fields["matter"].queryset = matter_list

    context = {
        "page": "activity",
        "edit": False,
        "add": True,
        "action": "/activity/add_expense",
        "form": form,
        "matter_list": matter_list,
    }

    return render(request, "activity/form_expense.html", context)


@login_required
def edit(request, id):
    entry = get_object_or_404(TimeEntry, pk=id)

    if request.method == "POST":
        form = TimeEntryForm(request.POST, instance=entry)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.save()
            return redirect("/activity")

    else:
        # get list of matters for activity form
        matter_list = Matter.objects.filter(status="Open").order_by("name")

        selected_matter = Matter.objects.filter(id=entry.matter.id)
        if selected_matter.first().status == "Closed":
            matter_list |= selected_matter

        # initialize form
        form = TimeEntryForm(instance=entry)

        # set the form fields
        form.fields["matter"].queryset = matter_list

        matter_rates = {}
        for matter in matter_list:
            try:
                rate = Rate.objects.filter(matter=matter, user=request.user).get()
                matter_rates.update({matter.id: rate.matter_rate})
            except ObjectDoesNotExist:
                matter_rates.update({matter.id: request.user.user_rate})

    context = {
        "page": "activity",
        "edit": True,
        "add": False,
        "action": f"/activity/{id}/edit",
        "entry": entry,
        "form": form,
        "matter_list": matter_list,
        "matter_rates": matter_rates,
    }

    return render(request, "activity/form.html", context)


@login_required
def edit_expense(request, id):
    entry = get_object_or_404(ExpenseEntry, pk=id)

    if request.method == "POST":
        form = ExpenseEntryForm(request.POST, instance=entry)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.save()
            return redirect("/activity")

    else:
        # get list of matters for activity form
        matter_list = Matter.objects.filter(status="Open").order_by("name")

        selected_matter = Matter.objects.filter(id=entry.matter.id)
        if selected_matter.first().status == "Closed":
            matter_list |= selected_matter

        # initialize form
        form = ExpenseEntryForm(instance=entry)

        # set the form fields
        form.fields["matter"].queryset = matter_list

    context = {
        "page": "activity",
        "edit": True,
        "add": False,
        "action": f"/activity/{id}/edit_expense",
        "entry": entry,
        "form": form,
        "matter_list": matter_list,
    }

    return render(request, "activity/form_expense.html", context)


@login_required
def delete(request, id):
    entry = get_object_or_404(TimeEntry, pk=id)
    entry.delete()
    return redirect("/activity")


@login_required
def delete_expense(request, id):
    entry = get_object_or_404(ExpenseEntry, pk=id)
    entry.delete()
    return redirect("/activity")


@login_required
def toggle_entered(request, id):
    entry = get_object_or_404(TimeEntry, pk=id)
    if entry.entered == 1:
        entry.entered = 0
    else:
        entry.entered = 1
    entry.save()
    return redirect("/activity")


@login_required
def toggle_entered_expense(request, id):
    entry = get_object_or_404(ExpenseEntry, pk=id)
    if entry.entered == 1:
        entry.entered = 0
    else:
        entry.entered = 1
    entry.save()
    return redirect("/activity")


@login_required
def export(request):
    import csv

    from django.http import HttpResponse

    # Create the HttpResponse object with the appropriate CSV header.
    response = HttpResponse(
        content_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="time_entries.csv"'},
    )

    entries = TimeEntry.objects.all()
    entries = entries.filter(matter__firm="Campbell & Brannon")
    entries = entries.exclude(matter__clio_matter_id__isnull=True)
    entries = entries.filter(entered=0)
    entries = entries.order_by("-date", "-id")

    writer = csv.writer(response)
    writer.writerow(
        [
            "matter",
            "date",
            "activity_description",
            "note",
            "price",
            "quantity",
            "type",
            "activity_user",
            "non-billable",
        ]
    )

    for entry in entries:

        clio_user = ""

        if entry.user.symbol == "JC":
            clio_user = "James Craig"

        if entry.user.symbol == "PL":
            clio_user = "Julia Taylor"

        writer.writerow(
            [
                entry.matter.clio_matter_id,
                entry.date.strftime("%m/%d/%Y"),
                "",
                entry.actions,
                entry.rate,
                entry.hours,
                "TimeEntry",
                clio_user,
                entry.comp,
            ]
        )

    entries = ExpenseEntry.objects.all()
    entries = entries.filter(matter__firm="Campbell & Brannon")
    entries = entries.exclude(matter__clio_matter_id="")
    entries = entries.filter(entered=0)
    entries = entries.order_by("-date", "-id")

    for entry in entries:

        clio_user = ""

        if entry.user.symbol == "JC":
            clio_user = "James Craig"

        if entry.user.symbol == "PL":
            clio_user = "Julia Taylor"

        writer.writerow(
            [
                entry.matter.clio_matter_id,
                entry.date.strftime("%m/%d/%Y"),
                "",
                entry.description,
                entry.amount,
                "1",
                "ExpenseEntry",
                clio_user,
                entry.comp,
            ]
        )

    return response


@login_required
def toggle_entries(request, entry_type):
    filter = Filter(request)
    filter.toggle_entries(request, entry_type)
    return redirect("/activity")
