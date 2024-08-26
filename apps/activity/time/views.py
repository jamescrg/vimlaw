from datetime import date, datetime

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import CustomUser
from apps.activity.expenses.models import ExpenseEntry
from apps.matters.models import Matter
from apps.matters.rates.models import Rate

from .export import write_clio_csv, write_standard_csv
from .filter import TimeEntryFilter
from .forms import TimeEntryForm
from .models import TimeEntry
from .summary import calculate_summary


@login_required
def time_list(request):
    """
    Display a list of activity entries

    Loads an instance of Filter, which holds a list of paramaters defining
    which entries to display.

    Calls the "calculate_summary" function to calculate totals of
    hours and fees.
    """

    entries = TimeEntry.objects.all()
    number_entries = entries.count()

    filter_data = request.session.get("time_filter", None)

    if filter_data:
        filter = TimeEntryFilter(filter_data)
        entries = filter.qs

        user_id = filter_data.get("user")
        user_id = int(user_id) if user_id not in (None, "") else None
    else:
        entries = TimeEntry.objects.all().order_by("date", "id")
        user_id = None

    summary = calculate_summary(entries)
    users = CustomUser.objects.filter(is_active=True)

    page = request.GET.get("page")
    pagination = Paginator(entries, per_page=10).get_page(page)

    context = {
        "page": "activity",
        "subpage": "time",
        "edit": False,
        "objects": pagination.object_list,
        "pagination": pagination,
        "number_entries": number_entries,
        "summary": summary,
        "users": users,
        "user_id": user_id,
    }

    return render(request, "activity/time/list.html", context)


@login_required
def time_filter(request):
    def get_filter(request):
        filter_data = request.session.get("time_filter", request.POST)

        return TimeEntryFilter(filter_data, queryset=TimeEntry.objects.all())

    if request.method == "POST":
        request.session["time_filter"] = request.POST

        return redirect("activity:time-list")

    else:
        filter = get_filter(request)

        return render(
            request,
            "activity/time/filter.html",
            {"filter": filter},
        )


@login_required
def time_filter_matter(request, matter_id):
    filter_data = request.session.get("time_filter", {})

    new_values = {
        "date_min": "",
        "date_max": "",
        "firm": None,
        "matter": matter_id,
        "keyword": "",
        "comp": None,
        "entered": None,
        "invoice": None,
    }

    for key, val in new_values.items():
        filter_data[key] = val

    filter_data["matter"] = matter_id

    request.session["time_filter"] = filter_data

    return redirect("activity:time-list")


@login_required
def time_filter_quick(request, quick_filter):
    quick_filters = {
        "unbilled": {
            "date_min": "",
            "date_max": "",
            "firm": "Campbell & Brannon",
            "matter": None,
            "keyword": "",
            "comp": None,
            "entered": 0,
            "invoice": 0,
        },
        "today": {
            "date_min": date.today().strftime("%Y-%m-%d"),
            "date_max": date.today().strftime("%Y-%m-%d"),
            "firm": "Campbell & Brannon",
            "matter": None,
            "keyword": "",
            "comp": None,
            "entered": None,
            "invoice": None,
        },
    }

    filter_data = {}
    for key, val in quick_filters[quick_filter].items():
        filter_data[key] = val

    request.session["time_filter"] = filter_data
    request.session.modified = True

    return redirect("activity:time-list")


@login_required
def time_filter_user(request):
    filter_data = request.session.get("time_filter", {})
    user = request.POST.get("user")
    filter_data["user"] = user
    request.session["time_filter"] = filter_data
    return redirect("activity:time-list")


@login_required
def time_add(request, id=None):
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
        "action": "/activity/time/add",
        "form": form,
        "matter_list": matter_list,
        "matter_rates": matter_rates,
    }

    return render(request, "activity/time/form.html", context)


@login_required
def time_edit(request, id):
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
        "action": f"/activity/time/{id}/edit",
        "entry": entry,
        "form": form,
        "matter_list": matter_list,
        "matter_rates": matter_rates,
    }

    return render(request, "activity/time/form.html", context)


@login_required
def time_delete(request, id):
    entry = get_object_or_404(TimeEntry, pk=id)
    entry.delete()
    return redirect("/activity")


@login_required
def time_toggle_entered(request, id):
    entry = get_object_or_404(TimeEntry, pk=id)
    if entry.entered == 1:
        entry.entered = 0
    else:
        entry.entered = 1
    entry.save()
    return redirect("/activity")


@login_required
def export_old(request):
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
def time_export_to_csv(request, format):

    # Set the file name
    current_day_and_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    filename = f"Time Entries - {current_day_and_time} - {format.title()}"

    # Create the HttpResponse object with the appropriate CSV header.
    response = HttpResponse(
        content_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

    # get the time entries per the user filter
    entries = TimeEntry.objects.all()
    filter_data = request.session.get("time_filter", None)
    if filter_data:
        filter = TimeEntryFilter(filter_data)
        entries = filter.qs
    else:
        entries = TimeEntry.objects.all().order_by("date", "id")

    # write the time entries to CSV
    if format == "clio":
        write_clio_csv(entries, response)
    else:
        write_standard_csv(entries, response)

    return response
