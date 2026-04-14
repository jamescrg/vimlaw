from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import DecimalField, ExpressionWrapper, F, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import render

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.matters.models import Matter


def _get_wip_data(sort_by="matter_name", sort_direction="asc"):
    """Build unbilled WIP data grouped by matter using bulk aggregation."""
    DECIMAL = DecimalField(max_digits=10, decimal_places=2)
    ZERO = Value(0, output_field=DECIMAL)
    fee_expr = ExpressionWrapper(F("hours") * F("rate"), output_field=DECIMAL)

    # Unbilled time entries: no invoice and not entered
    time_by_matter = (
        TimeEntry.objects.filter(
            invoice__isnull=True, entered=False, matter__billable=True
        )
        .values("matter__id", "matter__name", "matter__client__name")
        .annotate(
            unbilled_hours=Coalesce(Sum("hours"), ZERO, output_field=DECIMAL),
            unbilled_fees=Coalesce(Sum(fee_expr), ZERO, output_field=DECIMAL),
        )
    )

    # Unbilled expense entries: no invoice and not entered
    expenses_by_matter = (
        ExpenseEntry.objects.filter(
            invoice__isnull=True, entered=False, matter__billable=True
        )
        .values("matter__id")
        .annotate(unbilled_expenses=Sum("amount"))
    )

    # Build lookup for expenses
    expense_lookup = {
        row["matter__id"]: row["unbilled_expenses"] or 0 for row in expenses_by_matter
    }

    # Collect all matter IDs that have unbilled expenses but no time entries
    time_matter_ids = set()
    results = []

    for row in time_by_matter:
        matter_id = row["matter__id"]
        time_matter_ids.add(matter_id)
        expenses = expense_lookup.pop(matter_id, 0)
        hours = row["unbilled_hours"] or 0
        fees = row["unbilled_fees"] or 0
        total = fees + expenses

        results.append(
            {
                "matter_id": matter_id,
                "matter_name": row["matter__name"] or "Unknown",
                "client_name": row["matter__client__name"] or "",
                "unbilled_hours": hours,
                "unbilled_fees": fees,
                "unbilled_expenses": expenses,
                "total_wip": total,
            }
        )

    # Add matters that only have unbilled expenses (no time entries)
    if expense_lookup:
        expense_only_matters = Matter.objects.filter(
            id__in=expense_lookup.keys(), billable=True
        ).select_related("client")
        for matter in expense_only_matters:
            expenses = expense_lookup[matter.id]
            results.append(
                {
                    "matter_id": matter.id,
                    "matter_name": matter.name or "Unknown",
                    "client_name": matter.client.name if matter.client else "",
                    "unbilled_hours": 0,
                    "unbilled_fees": 0,
                    "unbilled_expenses": expenses,
                    "total_wip": expenses,
                }
            )

    # Calculate totals
    totals = {
        "unbilled_hours": sum(r["unbilled_hours"] for r in results),
        "unbilled_fees": sum(r["unbilled_fees"] for r in results),
        "unbilled_expenses": sum(r["unbilled_expenses"] for r in results),
        "total_wip": sum(r["total_wip"] for r in results),
    }

    # Sort
    reverse_sort = sort_direction == "desc"
    if sort_by == "matter_name":
        results.sort(key=lambda x: x["matter_name"].lower(), reverse=reverse_sort)
    elif sort_by == "client_name":
        results.sort(key=lambda x: x["client_name"].lower(), reverse=reverse_sort)
    else:
        results.sort(key=lambda x: x.get(sort_by, 0), reverse=reverse_sort)

    return results, totals


@login_required
@staff_member_required
def wip_index(request):
    sort_by = request.GET.get("sort", "matter_name")
    sort_direction = request.GET.get("direction", "asc")
    wip_data, totals = _get_wip_data(sort_by, sort_direction)

    context = {
        "app": "reports",
        "subapp": "wip",
        "wip_data": wip_data,
        "totals": totals,
        "current_sort": sort_by,
        "current_direction": sort_direction,
    }
    return render(request, "reports/wip/main.html", context)


@login_required
@staff_member_required
def wip_list(request):
    sort_by = request.GET.get("sort", "matter_name")
    sort_direction = request.GET.get("direction", "asc")
    wip_data, totals = _get_wip_data(sort_by, sort_direction)

    context = {
        "app": "reports",
        "subapp": "wip",
        "wip_data": wip_data,
        "totals": totals,
        "current_sort": sort_by,
        "current_direction": sort_direction,
    }
    return render(request, "reports/wip/list.html", context)
