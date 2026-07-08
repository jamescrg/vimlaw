from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.accounts.access import filter_matters_for_user, matter_access_required
from apps.calendar.models import Event
from apps.contacts.models import Contact
from apps.matters.filter import MatterFilter
from apps.matters.forms import MatterForm
from apps.matters.get_matter_list import get_matter_list
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding
from apps.matters.settlement.models import SettlementEntry

# Valid detail tabs for the matter detail view
VALID_DETAIL_TABS = [
    "overview",
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


def _matter_overview_context(request, matter):
    """Shared context for the Overview tab (full page + HTMX partial). The
    firm's default jurisdiction (Firm.jurisdiction) is shown when the matter
    has none; recent_actions feeds the Recent Actions table (the latest time
    entries, newest first). The financial snapshot reuses the Ledger tab's
    authorities (get_ledger_data / the trust app) and, like that tab, is
    reserved for admin/perm_financial users."""
    from apps.activity.time.models import TimeEntry
    from apps.matters.ledger.get_ledger_data import get_ledger_data
    from apps.matters.models import PracticeArea
    from apps.settings.models import Firm
    from apps.trust.available import client_trust_available

    company = Firm.objects.first()
    show_financial = request.user.is_admin or request.user.perm_financial
    today = date.today()
    context = {
        "company_jurisdiction": company.jurisdiction if company else "",
        "show_financial": show_financial,
        # Options for the inline practice-area dropdown.
        "practice_areas": PracticeArea.objects.order_by("name"),
        "recent_actions": (
            TimeEntry.objects.filter(matter=matter)
            .select_related("user")
            .order_by("-date", "-id")[:5]
        ),
        # Dash-style upcoming-events cards, scoped to this matter.
        "upcoming_events": (
            Event.objects.filter(
                matter=matter, status="Pending", date__gte=today
            ).order_by("date", "start_time", "party")[:7]
        ),
        "today": today,
        "tomorrow": today + timedelta(days=1),
    }
    if show_financial:
        context["balance_due"] = get_ledger_data(matter)["balance_due"]
        context["trust_available"] = client_trust_available(matter.client_id)
    return context


@login_required
@matter_access_required
def overview_index(request, id):
    """Full-page render of the matter Overview tab (matter properties + client)."""
    matter = get_object_or_404(Matter, pk=id)
    context = {
        "app": "matters",
        "subapp": "overview",
        "matter": matter,
        **_matter_overview_context(request, matter),
    }
    return render(request, "matters/overview/list.html", context)


@login_required
@matter_access_required
def overview_status_update(request, id, status):
    """Save a Status dropdown pick and re-render the cell. Also fires
    mattersChanged: Open/Closed flips change the open-matters switcher and
    stepper lists."""
    matter = get_object_or_404(Matter, pk=id)
    if status in dict(MatterForm.Meta.STATUSES):
        matter.status = status
        matter.save()
    response = render(request, "matters/overview/status.html", {"matter": matter})
    response["HX-Trigger"] = "mattersChanged"
    return response


@login_required
@matter_access_required
def overview_practice_area_update(request, id, practice_area_id):
    """Save a Practice Area dropdown pick and re-render the cell."""
    from apps.matters.models import PracticeArea

    matter = get_object_or_404(Matter, pk=id)
    matter.practice_area = get_object_or_404(PracticeArea, pk=practice_area_id)
    matter.save()
    return render(
        request,
        "matters/overview/practice-area.html",
        {"matter": matter, "practice_areas": PracticeArea.objects.order_by("name")},
    )


@login_required
@matter_access_required
def overview_description_edit(request, matter_id):
    """Inline description editor for the Overview tab (swaps the cell to an input)."""
    matter = get_object_or_404(Matter, pk=matter_id)
    return render(request, "matters/overview/description-edit.html", {"matter": matter})


@login_required
@matter_access_required
def overview_description_update(request, id):
    """Save the inline description edit and swap the cell back to the display."""
    matter = get_object_or_404(Matter, pk=id)
    matter.description = request.POST.get("description", "")
    matter.save()
    return render(request, "matters/overview/description.html", {"matter": matter})


@login_required
@matter_access_required
def overview_work_status_edit(request, matter_id):
    """Inline work-status editor for the Overview tab (swaps the cell to an input)."""
    matter = get_object_or_404(Matter, pk=matter_id)
    return render(request, "matters/overview/work-status-edit.html", {"matter": matter})


@login_required
@matter_access_required
def overview_work_status_update(request, id):
    """Save the inline work-status edit and swap the cell back to the display."""
    matter = get_object_or_404(Matter, pk=id)
    matter.work_status = request.POST.get("work_status", "")
    matter.save()
    return render(request, "matters/overview/work-status.html", {"matter": matter})


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
    from apps.matters.activity.views import get_matter_activity_data
    from apps.matters.contacts.views import get_contact_list
    from apps.matters.events.get_event_data import get_event_data
    from apps.matters.ledger.get_ledger_data import get_ledger_data
    from apps.matters.rates.models import Rate
    from apps.matters.tasks.views import get_matter_tasks_data
    from apps.trust.available import client_trust_available
    from apps.trust.trust import get_pending_client_balance

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

    if tab == "overview":
        return {
            "tab_template": "matters/overview/main.html",
            **_matter_overview_context(request, matter),
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
        return {
            "tab_template": "matters/activity/list.html",
            **get_matter_activity_data(request, matter),
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
            client_trust_balance = get_pending_client_balance(matter.client.id)

        total_cost = (
            matter.value["invoices"]["payment_sum"]
            + ledger_data["balance_due"]
            + matter.value["unbilled"]["net_fees_and_expenses"]
        )

        # A matter's trust available IS its client's (pooled trust) — the single
        # authoritative, pending-based figure from the trust app.
        trust_available = client_trust_available(matter.client_id)

        return {
            "tab_template": "matters/ledger/list.html",
            "client_trust_balance": client_trust_balance,
            "total_cost": total_cost,
            "trust_available": trust_available,
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
            # Clean 204 closes the modal (and clears its backdrop) via the
            # standard path. mattersChanged refreshes the matters list and the
            # self-refreshing matter switcher in the detail header (so the name
            # updates) — no modal-targeted body, which is what left the backdrop.
            return HttpResponse(status=204, headers={"HX-Trigger": "mattersChanged"})

    else:
        form = MatterForm(instance=matter)

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
def client_search(request):
    """Typeahead search for the add/edit matter client picker: all contacts by
    name. Renders the client-results partial (results + create/convert footer)."""
    text = request.POST.get("search_text")
    contacts = (
        Contact.objects.filter(name__icontains=text).order_by("name") if text else None
    )
    return render(
        request, "matters/contacts/client-results.html", {"contacts": contacts}
    )


@login_required
def switcher(request, id):
    """Return the matter-switcher partial (header name + open-matter dropdown).
    The detail header's switcher re-fetches this on mattersChanged so the name
    updates after an edit, without a modal-targeted response."""
    matter = get_object_or_404(Matter, pk=id)
    return render(
        request,
        "matters/includes/switcher.html",
        {"matter": matter, "mode": "detail"},
    )


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
def open_matters_json(request):
    """Return open matters as JSON for the keyboard-driven matter switcher."""
    matters = Matter.objects.filter(status="Open").order_by("name")
    matters = filter_matters_for_user(matters, request.user)
    data = [{"id": m.id, "name": m.name} for m in matters]
    return JsonResponse(data, safe=False)
