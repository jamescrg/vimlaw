from datetime import date, datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.activity.expenses.get_expenses_data import get_expenses_data
from apps.management.selection import (
    clear_selected_ids,
    get_selected_ids,
    get_session_key,
    select_all_ids,
    selection_response,
    toggle_id,
)
from apps.matters.models import Matter

from .export import write_clio_csv, write_standard_csv
from .filter import ExpenseFilter
from .forms import ExpenseEntryForm
from .models import ExpenseEntry


@login_required
def expenses_index(request):
    expenses_data = get_expenses_data(request)

    context = {
        "app": "activity",
        "subapp": "expenses",
    } | expenses_data

    return render(request, "activity/expenses/main.html", context)


@login_required
def expenses_list(request):
    """
    Display a list of activity expenses

    Loads an instance of Filter, which holds a list of paramaters defining
    which expenses to display.

    Calls the "calculate_summary" function to calculate totals of
    hours and fees.
    """
    expenses_data = get_expenses_data(request)

    context = {
        "app": "activity",
        "subapp": "expenses",
    }

    context = context | expenses_data

    return render(request, "activity/expenses/list.html", context)


@login_required
def expenses_filter(request):
    def get_filter(request):
        filter_data = request.session.get("expenses_filter", request.POST)
        # Strip the legacy "All Users" sentinel (0) before binding the form.
        if filter_data.get("user") in (0, "0"):
            filter_data = dict(filter_data)
            filter_data.pop("user", None)
            request.session["expenses_filter"] = filter_data
        return ExpenseFilter(filter_data, queryset=ExpenseEntry.objects.all())

    if request.method == "POST":
        filter_data = {}
        for key, val in request.POST.items():
            filter_data[key] = val
        filter_data["filter_label"] = "custom"
        request.session["expenses_filter"] = filter_data
        return HttpResponse(status=204, headers={"HX-Trigger": "expensesChanged"})

    else:
        filter = get_filter(request)
        return render(request, "activity/expenses/filter.html", {"filter": filter})


@login_required
def expenses_filter_quick(request, quick_filter):
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    quick_filters = {
        "all": {"date_min": "", "date_max": "", "filter_label": "all"},
        "unbilled": {
            "date_min": "",
            "date_max": "",
            "entered": 0,
            "invoice": 0,
            "filter_label": "unbilled",
        },
        "today": {
            "date_min": str(today),
            "date_max": str(today),
            "filter_label": "today",
        },
        "yesterday": {
            "date_min": str(today - timedelta(days=1)),
            "date_max": str(today - timedelta(days=1)),
            "filter_label": "yesterday",
        },
        "this_week": {
            "date_min": str(monday),
            "date_max": str(today),
            "filter_label": "this_week",
        },
        "this_month": {
            "date_min": str(month_start),
            "date_max": str(today),
            "filter_label": "this_month",
        },
    }

    filter_data = request.session.get("expenses_filter", {})
    filter_data.update(quick_filters[quick_filter])

    if quick_filter != "unbilled" and filter_data.get("entered") == 0:
        filter_data.pop("entered", None)
        filter_data.pop("invoice", None)

    request.session["expenses_filter"] = filter_data
    request.session.modified = True

    return HttpResponse(status=204, headers={"HX-Trigger": "expensesChanged"})


@login_required
def expenses_filter_user(request, user_id):
    filter_data = request.session.get("expenses_filter", {})
    # See time_filter_user: 0 is the "All Users" sentinel. Clear instead
    # of storing it so the ModelChoiceFilter doesn't trip on validation.
    if user_id == 0:
        filter_data.pop("user", None)
    else:
        filter_data["user"] = user_id

    request.session["expenses_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "expensesChanged"})


@login_required
def order_by_expenses(request, order):
    filter_data = request.session.get("expenses_filter", {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["expenses_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "expensesChanged"})


@login_required
def expenses_add(request, id=None, request_app="activity"):
    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = ExpenseEntryForm(request.POST, user=request.user)
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

            if request_app == "activity":
                return HttpResponse(
                    status=204, headers={"HX-Trigger": "expensesChanged"}
                )
            elif request_app in ("matters", "case"):
                url = reverse("activity:expenses-index")
                return HttpResponse(status=200, headers={"HX-Redirect": url})

    # if no post data has been submitted, show the entry form
    else:
        today = date.today().strftime("%Y-%m-%d")
        if id:
            matter = get_object_or_404(Matter, pk=id)
            form = ExpenseEntryForm(
                initial={
                    "date": today,
                    "matter": matter,
                },
                user=request.user,
            )
        else:
            form = ExpenseEntryForm(initial={"date": today}, user=request.user)

    # get list of matters for activity form
    matter_list = Matter.objects.filter(
        status__in=["Pending", "Open", "Complete"]
    ).order_by("name")

    # if a single matter is selected,  pull that matter as a quersyset
    if id:
        selected_matter = Matter.objects.filter(id=id)

        # if the matter is closed, add it to the matter list
        # if it is open, don't add it; avoid creating two instances of the same matter
        if selected_matter.first().status == "Closed":
            matter_list |= selected_matter

    # set the form fields
    form.fields["matter"].queryset = matter_list

    # When no matter is pre-selected, autofocus the matter select instead of description
    if not id:
        form.fields["description"].widget.attrs.pop("autofocus", None)
        form.fields["matter"].widget.attrs["autofocus"] = "autofocus"

    context = {
        "app": "activity",
        "edit": False,
        "add": True,
        "action": "/activity/expenses/add",
        "form": form,
        "matter_list": matter_list,
        "matter_id": id,
    }

    if request_app == "activity":
        return render(request, "activity/expenses/form.html", context)
    elif request_app in ("matters", "case"):
        context["request_app"] = request_app
        return render(request, "matters/activity/expense-form.html", context)


@login_required
def expenses_edit(request, id):
    entry = get_object_or_404(ExpenseEntry, pk=id)

    if request.method == "POST":
        form = ExpenseEntryForm(request.POST, instance=entry, user=request.user)
        if form.is_valid():
            original_entry = get_object_or_404(ExpenseEntry, pk=id)
            entry = form.save(commit=False)

            # if the matter has been changed, be sure to clear the
            # entry off of any relevant invoice
            # this will not happen if the invoice has been approved,
            # because editing will be locked at that point
            if original_entry.matter != entry.matter:
                entry.invoice = None

            entry.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "expensesChanged"})

    else:
        # get list of matters for activity form
        matter_list = Matter.objects.filter(
            status__in=["Pending", "Open", "Complete"]
        ).order_by("name")

        selected_matter = Matter.objects.filter(id=entry.matter.id)
        if selected_matter.first().status == "Closed":
            matter_list |= selected_matter

        # initialize form
        form = ExpenseEntryForm(instance=entry, user=request.user)

        # set the form fields
        form.fields["matter"].queryset = matter_list

    context = {
        "app": "activity",
        "edit": True,
        "add": False,
        "action": f"/activity/expenses/{id}/edit",
        "entry": entry,
        "form": form,
        "matter_list": matter_list,
    }

    return render(request, "activity/expenses/form.html", context)


@login_required
def expenses_delete(request, id):
    entry = get_object_or_404(ExpenseEntry, pk=id)
    entry.delete()

    return HttpResponse(status=204, headers={"HX-Trigger": "expensesChanged"})


@login_required
def expenses_toggle_entered(request, id):
    entry = get_object_or_404(ExpenseEntry, pk=id)
    if entry.entered == 1:
        entry.entered = 0
    else:
        entry.entered = 1
    entry.save()
    return redirect("/activity/expenses")


@login_required
def expenses_export_to_csv(request, format):
    # Set the file name
    current_day_and_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    filename = f"Expenses - {current_day_and_time} - {format.title()}"

    # Create the HttpResponse object with the appropriate CSV header.
    response = HttpResponse(
        content_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )

    # get the time expenses per the user filter
    expenses = ExpenseEntry.objects.all()
    filter_data = request.session.get("expenses_filter", {})
    if filter_data:
        filter = ExpenseFilter(filter_data)
        expenses = filter.qs
    else:
        expenses = ExpenseEntry.objects.all().order_by("date", "id")

    # write the time expenses to CSV
    if format == "clio":
        write_clio_csv(expenses, response)
    else:
        write_standard_csv(expenses, response)

    return response


EXPENSES_TRIGGER = "expensesChanged"


@login_required
@require_POST
def expenses_toggle_select(request, entry_id):
    get_object_or_404(ExpenseEntry, pk=entry_id)
    toggle_id(request, get_session_key("selected_expenses"), entry_id)

    return selection_response(EXPENSES_TRIGGER)


@login_required
@require_POST
def expenses_select_all(request):
    expenses_data = get_expenses_data(request)
    visible_ids = [expense.id for expense in expenses_data["objects"]]

    select_all_ids(request, get_session_key("selected_expenses"), visible_ids)

    return selection_response(EXPENSES_TRIGGER)


@login_required
@require_POST
def expenses_clear_selection(request):
    clear_selected_ids(request, get_session_key("selected_expenses"))

    return selection_response(EXPENSES_TRIGGER)


@login_required
def expenses_bulk_update_matter(request):
    if not request.user.is_admin and not request.user.perm_financial:
        return HttpResponseForbidden()

    key = get_session_key("selected_expenses")
    selected_expenses = get_selected_ids(request, key)

    if not selected_expenses:
        return HttpResponse(status=400, content="No expense entries selected.")

    if request.method == "POST":
        matter_id = request.POST.get("matter")

        if matter_id:
            matter = get_object_or_404(Matter, pk=matter_id)
            entries = ExpenseEntry.objects.filter(id__in=selected_expenses)

            for entry in entries:
                # Clear invoice if matter changes
                entry.matter = matter
                entry.invoice = None

                entry.save()

            clear_selected_ids(request, key)
            return HttpResponse(status=204, headers={"HX-Trigger": EXPENSES_TRIGGER})

    matters = Matter.objects.filter(
        status__in=["Pending", "Open", "Complete"]
    ).order_by("name")

    context = {
        "selected_count": len(selected_expenses),
        "matters": matters,
        "entry_type": "expense",
    }

    return render(request, "activity/bulk-matter-form.html", context)


@login_required
def expenses_bulk_update_comp(request):
    if not request.user.is_admin and not request.user.perm_financial:
        return HttpResponseForbidden()

    key = get_session_key("selected_expenses")
    selected_expenses = get_selected_ids(request, key)

    if not selected_expenses:
        return HttpResponse(status=400, content="No expense entries selected.")

    if request.method == "POST":
        comp_value = request.POST.get("comp")
        if comp_value in ["true", "false"]:
            entries = ExpenseEntry.objects.filter(id__in=selected_expenses)
            comp_bool = comp_value == "true"

            for entry in entries:
                entry.comp = comp_bool
                entry.save()

            clear_selected_ids(request, key)
            return HttpResponse(status=204, headers={"HX-Trigger": EXPENSES_TRIGGER})

    context = {
        "selected_count": len(selected_expenses),
        "entry_type": "expense",
    }

    return render(request, "activity/bulk-comp-form.html", context)
