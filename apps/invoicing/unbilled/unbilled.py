from datetime import date

from django.db.models import DateField, DecimalField, F, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.invoicing.invoices.models import Invoice
from apps.management.pagination import CustomPaginator
from apps.management.selection import all_visible_selected, get_selected_ids
from apps.matters.models import Matter
from apps.trust.trust import get_confirmed_client_balance


def get_unbilled_data(request):
    """Get matters with any unbilled time or expenses."""
    unbilled_data = {}
    filter_data = request.session.get("unbilled_filter", {})
    activity_period = filter_data.get("activity_period", "")

    # Base filters for unbilled entries
    time_filters = {
        "matter": OuterRef("pk"),
        "entered": False,
        "invoice__isnull": True,
    }
    expense_filters = {
        "matter": OuterRef("pk"),
        "entered": False,
        "invoice__isnull": True,
    }

    # Apply activity period date cutoff
    if activity_period == "prior_month":
        cutoff = date.today().replace(day=1)
        time_filters["date__lt"] = cutoff
        expense_filters["date__lt"] = cutoff
    elif activity_period == "current_month":
        cutoff = date.today().replace(day=1)
        time_filters["date__gte"] = cutoff
        expense_filters["date__gte"] = cutoff

    # Use subqueries to avoid JOIN multiplication when aggregating multiple related tables
    unbilled_hours_subquery = (
        TimeEntry.objects.filter(**time_filters)
        .exclude(comp=True)
        .values("matter")
        .annotate(total=Sum("hours"))
        .values("total")
    )

    unbilled_fees_subquery = (
        TimeEntry.objects.filter(**time_filters)
        .exclude(comp=True)
        .values("matter")
        .annotate(total=Sum(F("hours") * F("rate")))
        .values("total")
    )

    unbilled_expenses_subquery = (
        ExpenseEntry.objects.filter(**expense_filters)
        .exclude(comp=True)
        .values("matter")
        .annotate(total=Sum("amount"))
        .values("total")
    )

    # Subquery for the most recent invoice date per matter
    last_invoice_subquery = (
        Invoice.objects.filter(matter=OuterRef("pk"))
        .order_by("-date_issued")
        .values("date_issued")[:1]
    )

    # Annotate matters with all unbilled time/fees and expenses
    matters = (
        Matter.objects.all()
        .annotate(
            unbilled_hours=Coalesce(
                Subquery(unbilled_hours_subquery, output_field=DecimalField()),
                0,
                output_field=DecimalField(),
            ),
            unbilled_fees=Coalesce(
                Subquery(unbilled_fees_subquery, output_field=DecimalField()),
                0,
                output_field=DecimalField(),
            ),
            unbilled_expenses=Coalesce(
                Subquery(unbilled_expenses_subquery, output_field=DecimalField()),
                0,
                output_field=DecimalField(),
            ),
            last_invoice_date=Subquery(last_invoice_subquery, output_field=DateField()),
        )
        .filter(Q(unbilled_hours__gt=0) | Q(unbilled_expenses__gt=0))
    )

    # Apply last invoice date filter
    last_invoice_before = filter_data.get("last_invoice_before")
    if last_invoice_before:
        cutoff = date.fromisoformat(last_invoice_before)
        matters = matters.filter(
            Q(last_invoice_date__lte=cutoff) | Q(last_invoice_date__isnull=True)
        )

    # Convert to list for pagination
    matters_list = list(matters)

    # Get unique clients and fetch trust balances once per client
    client_trust_balances = {}
    for matter in matters_list:
        if matter.client and matter.client.id not in client_trust_balances:
            try:
                client_trust_balances[matter.client.id] = get_confirmed_client_balance(
                    matter.client.id
                )
            except Exception:
                client_trust_balances[matter.client.id] = 0

    # Add calculated fields to each matter
    total_hours = 0
    total_fees = 0
    total_expenses = 0
    total_activity = 0
    total_trust = 0

    for matter in matters_list:
        # Get trust balance for this matter's client
        matter.trust_balance = (
            client_trust_balances.get(matter.client.id, 0) if matter.client else 0
        )

        # Calculate total activity (fees + expenses)
        matter.total_activity = matter.unbilled_fees + matter.unbilled_expenses

        # Add to totals
        total_hours += matter.unbilled_hours
        total_fees += matter.unbilled_fees
        total_expenses += matter.unbilled_expenses
        total_activity += matter.total_activity
        total_trust += matter.trust_balance

    # Handle sorting
    order_by = filter_data.get(
        "order_by", "-total_activity"
    )  # Default to activity descending

    # Sort the list based on order_by field
    reverse = order_by.startswith("-")
    sort_field = order_by.lstrip("-")

    if sort_field == "name":
        matters_list.sort(key=lambda m: m.name.lower(), reverse=reverse)
    elif sort_field == "total_activity":
        matters_list.sort(key=lambda m: m.total_activity, reverse=reverse)
    elif sort_field == "unbilled_fees":
        matters_list.sort(key=lambda m: m.unbilled_fees, reverse=reverse)
    elif sort_field == "last_invoice_date":
        matters_list.sort(
            key=lambda m: m.last_invoice_date or date.min, reverse=reverse
        )

    # Pagination
    pagination = CustomPaginator(
        matters_list,
        per_page=20,
        request=request,
        session_key="unbilled_pagination",
    )

    # Get current order and strip leading '-' for comparison
    current_order = order_by.lstrip("-")

    page_matters = pagination.get_object_list()
    visible_ids = [m.id for m in page_matters]
    selected_ids = get_selected_ids(request, "selected_unbilled")

    # Store visible IDs in session for select-all
    request.session["unbilled_visible_ids"] = visible_ids

    unbilled_data["matters"] = page_matters
    unbilled_data["matter_count"] = len(matters_list)
    unbilled_data["pagination"] = pagination
    unbilled_data["session_key"] = "unbilled_pagination"
    unbilled_data["trigger_key"] = "unbilledListChanged"
    unbilled_data["total_hours"] = total_hours
    unbilled_data["total_fees"] = total_fees
    unbilled_data["total_expenses"] = total_expenses
    unbilled_data["total_activity"] = total_activity
    unbilled_data["total_trust"] = total_trust
    unbilled_data["activity_period"] = activity_period
    unbilled_data["order_by"] = order_by
    unbilled_data["current_order"] = current_order
    unbilled_data["selected_ids"] = selected_ids
    unbilled_data["all_selected"] = all_visible_selected(selected_ids, visible_ids)
    unbilled_data["filter_label"] = filter_data.get("filter_label")

    return unbilled_data
