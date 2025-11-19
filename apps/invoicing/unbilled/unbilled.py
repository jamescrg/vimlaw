from django.db.models import DecimalField, F, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter
from apps.trust.trust import get_confirmed_client_balance


def get_unbilled_data(request):
    """Get matters with any unbilled time or expenses."""
    unbilled_data = {}

    # Use subqueries to avoid JOIN multiplication when aggregating multiple related tables
    unbilled_hours_subquery = (
        TimeEntry.objects.filter(
            matter=OuterRef("pk"),
            entered=0,
            invoice__isnull=True,
        )
        .exclude(comp=1)
        .values("matter")
        .annotate(total=Sum("hours"))
        .values("total")
    )

    unbilled_fees_subquery = (
        TimeEntry.objects.filter(
            matter=OuterRef("pk"),
            entered=0,
            invoice__isnull=True,
        )
        .exclude(comp=1)
        .values("matter")
        .annotate(total=Sum(F("hours") * F("rate")))
        .values("total")
    )

    unbilled_expenses_subquery = (
        ExpenseEntry.objects.filter(
            matter=OuterRef("pk"),
            entered=0,
            invoice__isnull=True,
        )
        .exclude(comp=1)
        .values("matter")
        .annotate(total=Sum("amount"))
        .values("total")
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
        )
        .filter(Q(unbilled_hours__gt=0) | Q(unbilled_expenses__gt=0))
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
    total_clearance = 0

    for matter in matters_list:
        # Get trust balance for this matter's client
        matter.trust_balance = (
            client_trust_balances.get(matter.client.id, 0) if matter.client else 0
        )

        # Calculate total activity (fees + expenses)
        matter.total_activity = matter.unbilled_fees + matter.unbilled_expenses

        # Calculate clearance (trust - total activity), but set to 0 if no trust balance
        if matter.trust_balance == 0:
            matter.clearance = 0
        else:
            matter.clearance = matter.trust_balance - matter.total_activity

        # Add to totals
        total_hours += matter.unbilled_hours
        total_fees += matter.unbilled_fees
        total_expenses += matter.unbilled_expenses
        total_activity += matter.total_activity
        total_trust += matter.trust_balance
        total_clearance += matter.clearance

    # Handle sorting
    filter_data = request.session.get("unbilled_filter", {})
    order_by = filter_data.get(
        "order_by", "-unbilled_fees"
    )  # Default to fees descending

    # Sort the list based on order_by field
    reverse = order_by.startswith("-")
    sort_field = order_by.lstrip("-")

    if sort_field == "name":
        matters_list.sort(key=lambda m: m.name.lower(), reverse=reverse)
    elif sort_field == "total_activity":
        matters_list.sort(key=lambda m: m.total_activity, reverse=reverse)
    elif sort_field == "clearance":
        matters_list.sort(key=lambda m: m.clearance, reverse=reverse)
    elif sort_field == "unbilled_fees":
        matters_list.sort(key=lambda m: m.unbilled_fees, reverse=reverse)

    # Pagination
    pagination = CustomPaginator(
        matters_list,
        per_page=20,
        request=request,
        session_key="unbilled_pagination",
    )

    unbilled_data["matters"] = pagination.get_object_list()
    unbilled_data["matter_count"] = len(matters_list)
    unbilled_data["pagination"] = pagination
    unbilled_data["session_key"] = "unbilled_pagination"
    unbilled_data["trigger_key"] = "unbilledListChanged"
    unbilled_data["total_hours"] = total_hours
    unbilled_data["total_fees"] = total_fees
    unbilled_data["total_expenses"] = total_expenses
    unbilled_data["total_activity"] = total_activity
    unbilled_data["total_trust"] = total_trust
    unbilled_data["total_clearance"] = total_clearance
    unbilled_data["order_by"] = order_by

    return unbilled_data
