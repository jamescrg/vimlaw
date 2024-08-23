from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import CustomUser
from apps.matters.models import Matter

from .filter import ExpenseFilter
from .forms import ExpenseEntryForm
from .models import ExpenseEntry
from .summary import calculate_summary


@login_required
def expenses_list(request):
    """
    Display a list of activity expenses

    Loads an instance of Filter, which holds a list of paramaters defining
    which expenses to display.

    Calls the "calculate_summary" function to calculate totals of
    hours and fees.
    """

    expenses = ExpenseEntry.objects.all()
    number_expenses = expenses.count()

    filter_data = request.session.get("expenses_filter", None)

    if filter_data:
        filter = ExpenseFilter(filter_data)
        expenses = filter.qs

        order = filter_data.get("order", "date, ascending")
        if order == "date, descending":
            expenses.order_by("-date", "-id")
        else:
            expenses.order_by("date", "id")

        user_id = filter_data.get("user")
        user_id = int(user_id) if user_id not in (None, "") else None
    else:
        expenses = ExpenseEntry.objects.all().order_by("date", "id")
        user_id = None

    summary = calculate_summary(expenses)
    users = CustomUser.objects.filter(is_active=True)
    page = request.GET.get("page")
    pagination = Paginator(expenses, per_page=10).get_page(page)

    context = {
        "page": "activity",
        "subpage": "expenses",
        "edit": False,
        "objects": pagination.object_list,
        "pagination": pagination,
        "number_expenses": number_expenses,
        "summary": summary,
        "users": users,
        "user_id": user_id,
    }

    return render(request, "activity/expenses/list.html", context)


@login_required
def expenses_filter(request):
    def get_filter(request):
        filter_data = request.session.get("expenses_filter", request.POST)

        return ExpenseFilter(filter_data, queryset=ExpenseEntry.objects.all())

    if request.method == "POST":
        request.session["expenses_filter"] = request.POST

        return redirect("activity:expenses-list")
    else:
        filter = get_filter(request)

        return render(request, "activity/expenses/filter.html", {"filter": filter})


@login_required
def expenses_filter_quick(request, quick_filter):

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
            "order": "date, ascending",
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
            "order": "date, descending",
        },
    }

    filter_data = {}
    for key, val in quick_filters[quick_filter].items():
        filter_data[key] = val

    request.session["expenses_filter"] = filter_data
    request.session.modified = True

    return redirect("activity:expenses-list")


@login_required
def expenses_filter_user(request):
    filter_data = request.session.get("expenses_filter", {})
    user = request.POST.get("user")
    filter_data["user"] = user
    request.session["expenses_filter"] = filter_data
    return redirect("activity:expenses-list")


@login_required
def expenses_add(request, id=None):
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
            return redirect("/activity/expenses")

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
        "action": "/activity/expenses/add",
        "form": form,
        "matter_list": matter_list,
    }

    return render(request, "activity/expenses/form.html", context)


@login_required
def expenses_edit(request, id):
    entry = get_object_or_404(ExpenseEntry, pk=id)

    if request.method == "POST":
        form = ExpenseEntryForm(request.POST, instance=entry)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.save()
            return redirect("/activity/expenses")

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
    return redirect("/activity/expenses")


@login_required
def expenses_toggle_entered(request, id):
    entry = get_object_or_404(ExpenseEntry, pk=id)
    if entry.entered == 1:
        entry.entered = 0
    else:
        entry.entered = 1
    entry.save()
    return redirect("/activity/expenses")
