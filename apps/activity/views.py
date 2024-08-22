from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import CustomUser
from apps.activity.filter_expenses import ExpenseFilter
from apps.activity.filter_time_entries import TimeEntryFilter
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

    entries = TimeEntry.objects.all()
    expense_entries = ExpenseEntry.objects.all()

    number_entries = entries.count()

    tab = "time"
    if request.session.get("activity-tab"):
        tab = request.session["activity-tab"]

    if tab == "time":
        filter_data = request.session.get("time_filter", None)

        if filter_data:
            filter = TimeEntryFilter(filter_data)
            entries = filter.qs
            if filter_data["order"] == "date, descending":
                entries = entries.order_by("-date", "-id")
            else:
                entries = entries.order_by("date", "id")

            user_id = filter_data.get("user")
            user_id = int(user_id) if user_id not in (None, "") else None
        else:
            entries = TimeEntry.objects.all().order_by("date", "id")
            user_id = None

    elif tab == "expenses":
        filter_data = request.session.get("expense_filter", None)

        if filter_data:
            filter = ExpenseFilter(filter_data)
            expense_entries = filter.qs
            if filter_data["order"] == "date, descending":
                entries.order_by("-date", "-id")
            else:
                entries.order_by("date", "id")

            user_id = filter_data.get("user")
            user_id = int(user_id) if user_id not in (None, "") else None
        else:
            expense_entries = ExpenseEntry.objects.all().order_by("date", "id")
            user_id = None

    summary = calculate_summary(entries, expense_entries)

    users = CustomUser.objects.all()

    page = request.GET.get("page")

    pagination = Paginator(
        entries if tab == "time" else expense_entries, per_page=10
    ).get_page(page)

    context = {
        "page": "activity",
        "edit": False,
        "objects": pagination.object_list,
        "pagination": pagination,
        "number_entries": number_entries,
        "summary": summary,
        "tab": tab,
        "users": users,
        "user_id": user_id,
    }

    return render(request, "activity/list.html", context)


@login_required
def time_entry_filter(request):
    def get_filter(request):
        filter_data = request.session.get("time_filter", request.POST)

        return TimeEntryFilter(filter_data, queryset=TimeEntry.objects.all())

    if request.method == "POST":
        request.session["time_filter"] = request.POST

        return redirect("activity:list")
    else:
        filter = get_filter(request)

        return render(request, "activity/time-entries-filter.html", {"filter": filter})


@login_required
def expenses_filter(request):
    def get_filter(request):
        filter_data = request.session.get("expense_filter", request.POST)

        return ExpenseFilter(filter_data, queryset=ExpenseEntry.objects.all())

    if request.method == "POST":
        request.session["expense_filter"] = request.POST

        return redirect("activity:list")
    else:
        filter = get_filter(request)

        return render(request, "activity/expenses-filter.html", {"filter": filter})


@login_required
def filter_matter(request, matter_id, tab):
    if tab == "time":
        filter_data = request.session.get("time_filter", {})
    elif tab == "expenses":
        filter_data = request.session.get("expense_filter", {})

    new_values = {
        "date_min": "",
        "date_max": "",
        "firm": None,
        "keyword": "",
        "comp": None,
        "entered": None,
        "invoice": None,
        "order": "date, ascending",
    }

    for key, val in new_values.items():
        filter_data[key] = val

    filter_data["matter"] = matter_id

    if tab == "time":
        request.session["time_filter"] = filter_data
    elif tab == "expenses":
        request.session["expense_filter"] = filter_data

    return redirect("activity:list")


@login_required
def quick_filter_unbilled(request, tab):
    if tab == "time":
        filter_data = request.session.get("time_filter", {})
    elif tab == "expenses":
        filter_data = request.session.get("expense_filter", {})

    new_values = {
        "firm": "Campbell & Brannon",
        "matter": None,
        "keyword": "",
        "comp": None,
        "order": "date, ascending",
    }

    for key, val in new_values.items():
        filter_data[key] = val

    filter_data["entered"] = 0
    filter_data["invoice"] = 0
    filter_data["date_min"] = ""
    filter_data["date_max"] = ""

    if tab == "time":
        request.session["time_filter"] = filter_data
    elif tab == "expenses":
        request.session["expense_filter"] = filter_data

    request.session.modified = True

    return redirect("activity:list")


@login_required
def quick_filter_today(request, tab):
    if tab == "time":
        filter_data = request.session.get("time_filter", {})
    elif tab == "expenses":
        filter_data = request.session.get("expense_filter", {})

    new_values = {
        "firm": "Campbell & Brannon",
        "matter": None,
        "order": "date, descending",
        "keyword": "",
        "comp": None,
        "entered": None,
        "invoice": None,
    }

    for key, val in new_values.items():
        filter_data[key] = val

    filter_data["date_min"] = date.today().strftime("%Y-%m-%d")
    filter_data["date_max"] = date.today().strftime("%Y-%m-%d")

    if tab == "time":
        request.session["time_filter"] = filter_data
    elif tab == "expenses":
        request.session["expense_filter"] = filter_data

    request.session.modified = True

    return redirect("activity:list")


@login_required
def quick_filter_user(request, tab):
    if tab == "time":
        filter_data = request.session.get("time_filter", {})
    elif tab == "expenses":
        filter_data = request.session.get("expense_filter", {})

    user = request.POST.get("user")
    filter_data["user"] = user

    if tab == "time":
        request.session["time_filter"] = filter_data
    elif tab == "expenses":
        request.session["expense_filter"] = filter_data

    return redirect("activity:list")


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

        if entry.user.symbol == "LK":
            clio_user = "Lexi Krier"

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

        if entry.user.symbol == "LK":
            clio_user = "Lexi Krier"

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
def set_tab(request, tab):
    request.session["activity-tab"] = tab
    request.session.modified = True
    return redirect("/activity")
