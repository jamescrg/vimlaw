from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.invoicing.invoices.models import Invoice
from apps.invoicing.unbilled.unbilled import get_unbilled_data
from apps.management.selection import (
    clear_selected_ids,
    get_selected_ids,
    select_all_ids,
    selection_response,
    toggle_id,
)
from apps.matters.models import Matter

UNBILLED_TRIGGER = "unbilledListChanged"
SESSION_KEY = "selected_unbilled"


@login_required
def unbilled_index(request):
    """Unbilled view."""
    context = get_unbilled_data(request)

    context = context | {
        "app": "invoicing",
        "subapp": "unbilled",
    }

    return render(request, "invoicing/unbilled/main.html", context)


@login_required
def unbilled_list(request):
    """Unbilled list view for HTMX."""
    context = get_unbilled_data(request)

    return render(request, "invoicing/unbilled/list.html", context)


@login_required
def unbilled_sort(request, order):
    """Handle sorting for unbilled list."""
    filter_data = request.session.get("unbilled_filter", {})

    current_order = filter_data.get("order_by", "")

    # Toggle sort direction if clicking the same column
    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["unbilled_filter"] = filter_data
    request.session.modified = True

    return redirect("invoicing:unbilled-list")


@login_required
def unbilled_filter(request):
    """Filter modal for unbilled list."""
    if request.method == "POST":
        filter_data = request.session.get("unbilled_filter", {})
        filter_data["last_invoice_before"] = request.POST.get("last_invoice_before", "")
        # activity_period is owned by the toolbar dropdown. Only overwrite it
        # when the modal posts a non-empty value, so applying the modal with
        # only a "last_invoice_before" change doesn't silently clear the
        # period the user picked from the dropdown.
        posted_period = request.POST.get("activity_period", "")
        if posted_period:
            filter_data["activity_period"] = posted_period
        order_by = request.POST.get("order_by", "")
        if order_by:
            filter_data["order_by"] = order_by
        filter_data["filter_label"] = "custom"
        request.session["unbilled_filter"] = filter_data

        return HttpResponse(status=204, headers={"HX-Trigger": UNBILLED_TRIGGER})

    filter_data = request.session.get("unbilled_filter", {})
    context = {
        "last_invoice_before": filter_data.get("last_invoice_before", ""),
        "activity_period": filter_data.get("activity_period", ""),
        "order_by": filter_data.get("order_by", "-total_activity"),
    }
    return render(request, "invoicing/unbilled/filter.html", context)


@login_required
def unbilled_filter_period(request, period):
    """Quick filter for activity period."""
    filter_data = request.session.get("unbilled_filter", {})
    filter_data["activity_period"] = period if period != "all" else ""
    filter_data.pop("filter_label", None)
    request.session["unbilled_filter"] = filter_data
    return HttpResponse(status=204, headers={"HX-Trigger": UNBILLED_TRIGGER})


@login_required
def unbilled_toggle_select(request, matter_id):
    """Toggle selection of a matter."""
    toggle_id(request, SESSION_KEY, matter_id)
    return selection_response(UNBILLED_TRIGGER)


@login_required
def unbilled_select_all(request):
    """Select or deselect all visible matters."""
    visible_ids = request.session.get("unbilled_visible_ids", [])
    select_all_ids(request, SESSION_KEY, visible_ids)
    return selection_response(UNBILLED_TRIGGER)


@login_required
def unbilled_clear_selection(request):
    """Clear all selections."""
    clear_selected_ids(request, SESSION_KEY)
    return selection_response(UNBILLED_TRIGGER)


@login_required
def unbilled_bulk_create_invoices(request):
    """Create invoices for all selected matters."""
    selected_ids = get_selected_ids(request, SESSION_KEY)

    if not selected_ids:
        return HttpResponse(status=400, content="No matters selected.")

    if request.method == "POST":
        date_limit = request.POST.get("date_limit")
        date_issued = request.POST.get("date_issued")

        if not date_limit or not date_issued:
            return HttpResponse(status=400, content="Both dates are required.")

        matters = Matter.objects.filter(id__in=selected_ids)
        for matter in matters:
            invoice = Invoice(
                matter=matter,
                date_limit=date_limit,
                date_issued=date_issued,
                created_by=request.user,
            )
            invoice.save()

        clear_selected_ids(request, SESSION_KEY)
        return HttpResponse(
            status=204,
            headers={"HX-Trigger": "invoicesChanged, unbilledListChanged"},
        )

    today = timezone.now().date()
    last_day_prev_month = today.replace(day=1) - timedelta(days=1)

    context = {
        "date_issued": today.isoformat(),
        "date_limit": last_day_prev_month.isoformat(),
        "selected_count": len(selected_ids),
    }
    return render(request, "invoicing/unbilled/bulk-create-form.html", context)
