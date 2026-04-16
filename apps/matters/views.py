from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.accounts.access import filter_matters_for_user, matter_access_required
from apps.calendar.models import Event
from apps.case.models import Fact
from apps.contacts.functions.load_contacts import load_contacts
from apps.contacts.models import Contact
from apps.matters.filter import MatterFilter
from apps.matters.forms import MatterForm
from apps.matters.get_matter_list import get_matter_list
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding
from apps.matters.settlement.models import SettlementEntry

# Valid detail tabs for the matter detail view
VALID_DETAIL_TABS = [
    "contacts",
    "rates",
    "activity",
    "events",
    "tasks",
    "proceedings",
    "settlement",
    "ledger",
]
DEFAULT_DETAIL_TAB = "contacts"


def get_detail_tab_session_key(matter_id):
    """Get the session key for storing the active detail tab for a matter."""
    return f"matter_detail_tab_{matter_id}"


def get_last_detail_tab(request, matter_id):
    """Get the last active detail tab for a matter, or default to contacts."""
    tab = request.session.get(get_detail_tab_session_key(matter_id), DEFAULT_DETAIL_TAB)
    return tab if tab in VALID_DETAIL_TABS else DEFAULT_DETAIL_TAB


def set_last_detail_tab(request, matter_id, tab):
    """Save the active detail tab for a matter."""
    if tab in VALID_DETAIL_TABS:
        request.session[get_detail_tab_session_key(matter_id)] = tab


@login_required
def matter_index(request):
    request.session["matters-view"] = "list"

    list_data = get_matter_list(request)

    context = {
        "app": "matters",
    } | list_data

    return render(request, "matters/main.html", context)


@login_required
def matter_list(request):
    request.session["matters-view"] = "list"

    list_data = get_matter_list(request)
    context = {
        "app": "matters",
    }

    context = context | list_data

    return render(request, "matters/list.html", context)


@login_required
def filter(request):
    def get_filter(request):
        filter_data = request.session.get("matter_filter", request.POST)
        return MatterFilter(filter_data, queryset=Matter.objects.all())

    if request.method == "POST":
        filter_data = {}
        for key, val in request.POST.items():
            filter_data[key] = val
        filter_data["filter_label"] = "custom"
        request.session["matter_filter"] = filter_data
        return HttpResponse(status=204, headers={"HX-Trigger": "mattersChanged"})

    else:
        filter = get_filter(request)
        return render(request, "matters/filter.html", {"filter": filter})


@login_required
def filter_quick(request, quick_filter):
    quick_filters = {
        "open": {
            "status": "Open",
            "filter_label": "open",
        },
    }

    filter_data = request.session.get("matter_filter", {})
    filter_data.update(quick_filters[quick_filter])

    request.session["matter_filter"] = filter_data
    request.session.modified = True

    return HttpResponse(status=204, headers={"HX-Trigger": "mattersChanged"})


@login_required
def filter_quick_status(request, status):
    filter_data = request.session.get("matter_filter", {})
    filter_data["status"] = status
    filter_data["filter_label"] = status
    request.session["matter_filter"] = filter_data
    return HttpResponse(status=204, headers={"HX-Trigger": "mattersChanged"})


@login_required
def quick_search(request):
    """Live search within current filter set, returns filtered rows."""
    query = request.GET.get("q", "").strip()

    default_filter = {
        "status": "Open",
        "practice_area": "",
        "date_start": "",
        "date_end": "",
        "order_by": "name",
    }
    filter_data = request.session.get("matter_filter", default_filter)

    # Apply the current filter (without ordering on computed fields)
    filter_data_copy = filter_data.copy()
    filter_data_copy.pop("order_by", None)
    matters = MatterFilter(filter_data_copy).qs
    matters = filter_matters_for_user(matters, request.user)

    if query:
        matters = matters.filter(name__icontains=query)

    matters = matters.order_by("name")

    # If Enter was pressed, redirect to top result
    if request.GET.get("enter") and matters.exists():
        url = reverse("matters:contacts", kwargs={"id": matters.first().id})
        return HttpResponse(status=200, headers={"HX-Redirect": url})

    return render(request, "matters/search-results.html", {"matters": matters})


@login_required
def order_by(request, order):
    filter_data = request.session.get("matter_filter", {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["matter_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "mattersChanged"})


@login_required
@matter_access_required
def detail(request, id):
    request.session["matters-view"] = "detail"
    tab = get_last_detail_tab(request, id)
    return redirect(f"/matters/{id}/{tab}")


@login_required
@matter_access_required
def mode_content(request, id):
    """Return detail mode content partial for HTMX, or redirect for regular request."""
    matter = get_object_or_404(Matter, pk=id)
    tab = get_last_detail_tab(request, id)

    if not request.headers.get("HX-Request"):
        return redirect(f"/matters/{id}/{tab}")

    context = {
        "matter": matter,
        "matters": Matter.objects.filter(status="Open").order_by("name"),
        "mode": "detail",
        "subapp": tab,
    }

    # Fetch tab data directly for single-request loading
    tab_data = _get_detail_tab_data(request, matter, tab)
    context.update(tab_data)

    return render(request, "matters/includes/detail-content.html", context)


@login_required
@matter_access_required
def tab_content(request, id, tab):
    """Return tab content with wrapper for HTMX tab switching."""
    matter = get_object_or_404(Matter, pk=id)

    # Update last viewed tab
    set_last_detail_tab(request, id, tab)

    context = {
        "matter": matter,
        "subapp": tab,
    }

    tab_data = _get_detail_tab_data(request, matter, tab)
    if tab_data.get("forbidden"):
        return HttpResponseForbidden()
    context.update(tab_data)

    return render(request, "matters/includes/detail-tab-content.html", context)


def _get_detail_tab_data(request, matter, tab):
    """Fetch data for the specified detail tab."""
    from apps.activity.time.models import TimeEntry
    from apps.activity.time.summary import calculate_summary
    from apps.management.pagination import CustomPaginator
    from apps.matters.contacts.views import get_contact_list
    from apps.matters.events.get_event_data import get_event_data
    from apps.matters.ledger.get_ledger_data import get_ledger_data
    from apps.matters.rates.models import Rate
    from apps.matters.tasks.views import get_matter_tasks_data
    from apps.trust.trust import get_confirmed_client_balance

    # Block financial tabs for users without perm_financial
    if (
        tab in ("ledger", "rates")
        and not request.user.is_admin
        and not request.user.perm_financial
    ):
        return {
            "tab_template": "matters/contacts/contact-table.html",
            "forbidden": True,
        }

    if tab == "contacts":
        return {
            "tab_template": "matters/contacts/contact-table.html",
            **get_contact_list(request, matter),
        }

    elif tab == "rates":
        return {
            "tab_template": "matters/rates/list.html",
            "rates": Rate.objects.filter(matter=matter).order_by("user__username"),
        }

    elif tab == "activity":
        sort_order = request.session.get("matter_activity_sort", "-id")
        entries = TimeEntry.objects.filter(matter=matter.id).order_by(sort_order)
        pagination = CustomPaginator(
            entries, per_page=10, request=request, session_key="activity_pagination"
        )
        return {
            "tab_template": "matters/activity/list.html",
            "entries": pagination.get_object_list(),
            "pagination": pagination,
            "session_key": "activity_pagination",
            "trigger_key": "matterActivityChanged",
            "summary": calculate_summary(entries),
        }

    elif tab == "events":
        return {
            "tab_template": "matters/events/list.html",
            **get_event_data(request, matter),
        }

    elif tab == "tasks":
        return {
            "tab_template": "matters/tasks/list.html",
            **get_matter_tasks_data(request, matter.id),
        }

    elif tab == "proceedings":
        return {
            "tab_template": "matters/proceedings/list.html",
            "proceedings": Proceeding.objects.filter(matter=matter.id).order_by(
                "date_filed"
            ),
        }

    elif tab == "settlement":
        return {
            "tab_template": "matters/settlement/list.html",
            "entries": SettlementEntry.objects.filter(matter=matter.id).order_by(
                "date"
            ),
        }

    elif tab == "ledger":
        ledger_data = get_ledger_data(matter)
        client_trust_balance = 0
        if matter.client:
            client_trust_balance = get_confirmed_client_balance(matter.client.id)

        total_cost = (
            matter.value["invoices"]["payment_sum"]
            + ledger_data["balance_due"]
            + matter.value["unbilled"]["net_fees_and_expenses"]
        )

        return {
            "tab_template": "matters/ledger/list.html",
            "client_trust_balance": client_trust_balance,
            "total_cost": total_cost,
            **ledger_data,
        }

    # Fallback
    return {"tab_template": "matters/contacts/contact-table.html"}


@login_required
def add(request):
    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = MatterForm(request.POST, use_required_attribute=False)
        if form.is_valid():
            matter = form.save(commit=False)
            matter.user_id = request.user.id
            matter.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "mattersChanged"})

    # if no post data has been submitted, show the matter form
    else:
        today = date.today().strftime("%Y-%m-%d")
        form = MatterForm(initial={"date_start": today}, use_required_attribute=False)
        client_list = Contact.objects.filter(client_status="Current").order_by("name")
        form.fields["client"].queryset = client_list

    context = {
        "app": "matters",
        "edit": False,
        "add": True,
        "action": "/matters/add",
        "form": form,
    }

    return render(request, "matters/form.html", context)


@login_required
@matter_access_required
def edit(request, id):
    matter = get_object_or_404(Matter, pk=id)

    if request.method == "POST":
        form = MatterForm(request.POST, instance=matter)
        if form.is_valid():
            matter = form.save(commit=False)
            matter.user_id = request.user.id
            matter.save()
            return HttpResponse(status=204, headers={"HX-Trigger": "mattersChanged"})

    else:
        form = MatterForm(instance=matter)
        client_list = Contact.objects.filter(client_status="Current").order_by("name")

        if matter.client:
            client_list |= Contact.objects.filter(pk=matter.client.pk)

        form.fields["client"].queryset = client_list

    context = {
        "app": "matters",
        "edit": True,
        "add": False,
        "action": f"/matters/{id}/edit",
        "matter": matter,
        "form": form,
    }

    return render(request, "matters/form.html", context)


@login_required
def delete(request, id):
    if not request.user.is_admin:
        return HttpResponseForbidden()
    matter = get_object_or_404(Matter, pk=id)

    if request.method == "GET":
        from apps.activity.expenses.models import ExpenseEntry
        from apps.activity.time.models import TimeEntry
        from apps.case.models import Document
        from apps.invoicing.invoices.models import Invoice
        from apps.notes.models import Note
        from apps.tasks.models import Task

        context = {
            "matter": matter,
            "time_entries_count": TimeEntry.objects.filter(matter=matter).count(),
            "expense_entries_count": ExpenseEntry.objects.filter(matter=matter).count(),
            "tasks_count": Task.objects.filter(matter=matter).count(),
            "documents_count": Document.objects.filter(matter=matter).count(),
            "notes_count": Note.objects.filter(matter=matter).count(),
            "events_count": Event.objects.filter(matter=matter).count(),
            "invoices_count": Invoice.objects.filter(matter=matter).count(),
        }

        return render(request, "matters/delete_confirmation.html", context)

    elif request.method == "DELETE":
        matter.delete()

        return HttpResponse(status=204, headers={"HX-Redirect": "/matters"})


@login_required
@matter_access_required
def edit_work_status(request, matter_id):
    matter = get_object_or_404(Matter, pk=matter_id)
    context = {"matter": matter}
    return render(request, "matters/edit-work-status.html", context)


@login_required
@matter_access_required
def update_work_status(request, id):
    matter = get_object_or_404(Matter, pk=id)
    matter.work_status = request.POST.get("work_status")
    matter.save()

    if request.session.get("matters-view"):
        if request.session["matters-view"] == "detail":
            return redirect(f"/matters/{matter.id}")
        if request.session["matters-view"] == "list":
            return render(request, "matters/row.html", {"matter": matter})
    else:
        return redirect("/matters")


@login_required
@matter_access_required
def print(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id, primary=True).first()
    relationship_groups = load_contacts(matter)
    events = Event.objects.filter(matter=id).order_by("-date")
    proceedings = Proceeding.objects.filter(matter=matter.id).order_by("date_filed")
    entries = SettlementEntry.objects.filter(matter=matter.id).order_by("date")
    facts = Fact.objects.filter(matter=matter.id).order_by("date")

    context = {
        "matter": matter,
        "proceeding": proceeding,
        "relationship_groups": relationship_groups,
        "events": events,
        "proceedings": proceedings,
        "entries": entries,
        "facts": facts,
    }

    return render(request, "matters/print.html", context)


@login_required
def open_matters_json(request):
    """Return open matters as JSON for the keyboard-driven matter switcher."""
    matters = Matter.objects.filter(status="Open").order_by("name")
    matters = filter_matters_for_user(matters, request.user)
    data = [{"id": m.id, "name": m.name} for m in matters]
    return JsonResponse(data, safe=False)
