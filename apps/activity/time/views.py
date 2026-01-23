from datetime import date, datetime

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.get_time_data import get_time_data
from apps.matters.models import Matter
from apps.matters.rates.models import Rate
from utils.toasts import toast_success

from .export import write_clio_csv, write_standard_csv
from .filter import TimeEntryFilter
from .forms import AbbreviationCodeForm, TimeEntryForm
from .models import AbbreviationCode, TimeEntry


def calculate_rate_for_matter(matter, user):
    """
    Calculate the appropriate rate for a matter and user.

    For Campbell & Brannon (client ID 1792), uses tiered billing:
    - First 25 hours/month: $175/hr (attorney), $75/hr (paralegal)
    - After 25 hours/month: $250/hr (attorney), $100/hr (paralegal)

    For other clients, uses matter rate or user rate.
    """
    # Special logic for Campbell & Brannon (client ID 1792)
    if matter.client and matter.client.id == 1792:
        from django.db.models import Sum

        # Get total hours billed to CB this month
        today = date.today()
        cb_hours = (
            TimeEntry.objects.filter(
                matter__client__id=1792,
                date__year=today.year,
                date__month=today.month,
            ).aggregate(Sum("hours"))["hours__sum"]
            or 0
        )

        # Determine rate based on threshold and user type
        if cb_hours < 25:
            return 175 if user.is_attorney else 75
        else:
            return 250 if user.is_attorney else 100
    else:
        # Standard logic for non-CB clients
        try:
            rate = Rate.objects.filter(matter=matter, user=user).get()
            return rate.matter_rate
        except ObjectDoesNotExist:
            return user.user_rate


@login_required
def time_index(request):
    time_data = get_time_data(request)

    context = {
        "app": "activity",
        "subapp": "time",
    } | time_data

    return render(request, "activity/time/main.html", context)


@login_required
def time_list(request):
    """
    Display a list of activity entries

    Loads an instance of Filter, which holds a list of paramaters defining
    which entries to display.

    Calls the "calculate_summary" function to calculate totals of
    hours and fees.
    """

    time_data = get_time_data(request)

    context = {
        "app": "activity",
        "subapp": "time",
    }

    context = context | time_data

    return render(request, "activity/time/list.html", context)


@login_required
def time_filter(request):
    def get_filter(request):
        filter_data = request.session.get("time_filter", request.POST)
        return TimeEntryFilter(filter_data, queryset=TimeEntry.objects.all())

    if request.method == "POST":
        filter_data = {}
        for key, val in request.POST.items():
            filter_data[key] = val
        filter_data["filter_label"] = "custom"
        request.session["time_filter"] = filter_data
        return HttpResponse(status=204, headers={"HX-Trigger": "timeChanged"})

    else:
        filter = get_filter(request)
        return render(
            request,
            "activity/time/filter.html",
            {"filter": filter},
        )


@login_required
def time_filter_matter(request, matter_id):
    time_filter_data = request.session.get("time_filter", {})
    expenses_filter_data = request.session.get("expenses_filter", {})

    new_values = {
        "date_min": "",
        "date_max": "",
        "firm": None,
        "matter": matter_id,
        "keyword": "",
        "comp": None,
        "entered": None,
        "invoice": None,
        "order_by": "date",
    }

    for key, val in new_values.items():
        time_filter_data[key] = val
        expenses_filter_data[key] = val

    time_filter_data["matter"] = matter_id
    expenses_filter_data["matter"] = matter_id

    request.session["time_filter"] = time_filter_data
    request.session["expenses_filter"] = expenses_filter_data

    return redirect("activity:time-index")


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
            "order_by": "date",
            "filter_label": "unbilled",
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
            "order_by": "-date",
            "filter_label": "today",
        },
    }

    filter_data = {}
    for key, val in quick_filters[quick_filter].items():
        filter_data[key] = val

    request.session["time_filter"] = filter_data
    request.session.modified = True

    # Support full page redirect via query param
    if request.GET.get("redirect"):
        return redirect("activity:time-index")

    return HttpResponse(status=204, headers={"HX-Trigger": "timeChanged"})


@login_required
def time_filter_user(request, user_id):
    filter_data = request.session.get("time_filter", {})
    filter_data["user"] = user_id

    request.session["time_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "timeChanged"})


@login_required
def order_by_time(request, order):
    filter_data = request.session.get("time_filter", {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["time_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "timeChanged"})


@login_required
def time_add(request, id=None, request_app="activity"):
    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = TimeEntryForm(request.POST)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.user_id = request.user.id

            # Apply abbreviation codes from database
            codes = AbbreviationCode.objects.filter(is_active=True)
            for code in codes:
                entry.actions = entry.actions.replace(code.code, code.expansion)

            entry.save()

            if request_app == "activity":
                return HttpResponse(status=204, headers={"HX-Trigger": "timeChanged"})
            elif request_app == "matters":
                return redirect("/activity")
            elif request_app == "case":
                response = HttpResponse(status=204)
                message = f"{entry.hours} hours recorded for {entry.matter.name}"
                link = {
                    "url": "/activity/time/filter/quick/today?redirect=1",
                    "text": "View Today",
                }
                return toast_success(
                    response, message, title="Time Entry Added", link=link
                )

    # if no post data has been submitted, show the entry form
    else:
        today = date.today().strftime("%Y-%m-%d")
        if id:
            matter = get_object_or_404(Matter, pk=id)
            rate = calculate_rate_for_matter(matter, request.user)

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
    matter_list = Matter.objects.filter(
        status__in=["Pending", "Open", "Complete"]
    ).order_by("name")

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
        "app": "activity",
        "edit": False,
        "add": True,
        "action": "/activity/time/add",
        "form": form,
        "matter_list": matter_list,
        "matter_id": id,
        "request_app": request_app,
    }

    if request_app == "activity":
        return render(request, "activity/time/form.html", context)
    elif request_app == "matters":
        return render(request, "matters/activity/time-form.html", context)
    elif request_app == "case":
        return render(request, "matters/activity/time-form.html", context)


@login_required
def time_edit(request, id):
    entry = get_object_or_404(TimeEntry, pk=id)

    if request.method == "POST":
        form = TimeEntryForm(request.POST, instance=entry)
        if form.is_valid():
            original_entry = get_object_or_404(TimeEntry, pk=id)
            entry = form.save(commit=False)

            # if the matter has been changed, be sure to clear the
            # entry off of any relevant invoice
            # this will not happen if the invoice has been approved,
            # because editing will be locked at that point
            if original_entry.matter != entry.matter:
                entry.invoice = None

            entry.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "timeChanged"})

    else:
        # get list of matters for activity form
        matter_list = Matter.objects.filter(
            status__in=["Pending", "Open", "Complete"]
        ).order_by("name")

        selected_matter = Matter.objects.filter(id=entry.matter.id)
        if selected_matter.first().status == "Closed":
            matter_list |= selected_matter

        # initialize form
        form = TimeEntryForm(instance=entry)

        # set the form fields
        form.fields["matter"].queryset = matter_list

    context = {
        "app": "activity",
        "edit": True,
        "add": False,
        "action": f"/activity/time/{id}/edit",
        "entry": entry,
        "form": form,
        "matter_list": matter_list,
    }

    return render(request, "activity/time/form.html", context)


@login_required
def time_delete(_, id):
    TimeEntry.objects.get(pk=id).delete()

    return HttpResponse(status=204, headers={"HX-Trigger": "timeChanged"})


@login_required
def time_toggle_entered(request, id):
    entry = get_object_or_404(TimeEntry, pk=id)
    entry.entered = not entry.entered
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
    entries = entries.filter(entered=False)
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

        if entry.user.initials == "JC":
            clio_user = "James Craig"

        if entry.user.initials == "LK":
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
    entries = entries.filter(entered=False)
    entries = entries.order_by("-date", "-id")

    for entry in entries:
        clio_user = ""

        if entry.user.initials == "JC":
            clio_user = "James Craig"

        if entry.user.initials == "LK":
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
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )

    # get the time entries per the user filter
    entries = TimeEntry.objects.all()
    filter_data = request.session.get("time_filter", {})
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


@login_required
def set_rate(request, matter_id):
    """
    AJAX endpoint to get the rate for a matter and return it as plain text

    For Campbell & Brannon (client ID 1792), uses tiered billing:
    - First 25 hours/month: $175/hr (attorney), $75/hr (paralegal)
    - After 25 hours/month: $250/hr (attorney), $100/hr (paralegal)
    """
    try:
        matter = Matter.objects.get(pk=matter_id)
        rate_value = calculate_rate_for_matter(matter, request.user)
    except Matter.DoesNotExist:
        rate_value = request.user.user_rate

    return HttpResponse(rate_value)


# ============================================================================
# Abbreviation Code Management Views
# ============================================================================


@login_required
def abbreviation_codes_list(request):
    """Display all abbreviation codes in a modal"""
    codes = AbbreviationCode.objects.filter(is_active=True).order_by("code")

    context = {"codes": codes}

    return render(request, "activity/time/codes/list.html", context)


@login_required
def abbreviation_code_add(request):
    """Add a new abbreviation code - Admin only"""
    # Check if user is admin
    if request.user.role != "ADMIN":
        return HttpResponse("Permission denied. Admin access required.", status=403)

    if request.method == "POST":
        form = AbbreviationCodeForm(request.POST)
        if form.is_valid():
            form.save()
            # Return the updated codes list to replace the form dialog
            codes = AbbreviationCode.objects.filter(is_active=True).order_by("code")
            return render(request, "activity/time/codes/list.html", {"codes": codes})
    else:
        form = AbbreviationCodeForm()

    context = {"form": form, "action": "/activity/time/codes/add/", "edit": False}

    return render(request, "activity/time/codes/form.html", context)


@login_required
def abbreviation_code_edit(request, id):
    """Edit an existing abbreviation code - Admin only"""
    # Check if user is admin
    if request.user.role != "ADMIN":
        return HttpResponse("Permission denied. Admin access required.", status=403)

    code = get_object_or_404(AbbreviationCode, pk=id)

    if request.method == "POST":
        form = AbbreviationCodeForm(request.POST, instance=code)
        if form.is_valid():
            form.save()
            # Return the updated codes list to replace the form dialog
            codes = AbbreviationCode.objects.filter(is_active=True).order_by("code")
            return render(request, "activity/time/codes/list.html", {"codes": codes})
    else:
        form = AbbreviationCodeForm(instance=code)

    context = {
        "form": form,
        "action": f"/activity/time/codes/{id}/edit/",
        "edit": True,
        "code": code,
    }

    return render(request, "activity/time/codes/form.html", context)


@login_required
def abbreviation_code_delete(request, id):
    """Delete (soft delete) an abbreviation code - Admin only"""
    # Check if user is admin
    if request.user.role != "ADMIN":
        return HttpResponse("Permission denied. Admin access required.", status=403)

    code = get_object_or_404(AbbreviationCode, pk=id)

    if request.method == "POST":
        # Soft delete by setting is_active to False
        code.is_active = False
        code.save()
        # Return the updated codes list to replace the delete confirmation dialog
        codes = AbbreviationCode.objects.filter(is_active=True).order_by("code")
        return render(request, "activity/time/codes/list.html", {"codes": codes})

    context = {"code": code}

    return render(request, "activity/time/codes/delete-confirm.html", context)


@login_required
def abbreviation_codes_json(request):
    """Return abbreviation codes as JSON for client-side preview"""
    from django.http import JsonResponse

    codes = (
        AbbreviationCode.objects.filter(is_active=True)
        .values("code", "expansion")
        .order_by("code")
    )
    codes_dict = {code["code"]: code["expansion"] for code in codes}

    return JsonResponse(codes_dict)


@login_required
def abbreviation_codes_reference(request):
    """Return abbreviation codes table for reference in time entry form"""
    codes = AbbreviationCode.objects.filter(is_active=True).order_by("code")
    return render(request, "activity/time/codes/reference.html", {"codes": codes})
