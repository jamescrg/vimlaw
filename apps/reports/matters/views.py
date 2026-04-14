from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import DecimalField, ExpressionWrapper, F, Sum, Value
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import render

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment
from apps.management.filter_manager import FilterManager
from apps.matters.models import Matter

from .filters import MatterSummaryFilter


def _get_matter_data(status_filter="Open", sort_by="matter_name", sort_direction="asc"):
    """Build per-matter financial summary using bulk aggregation."""
    DECIMAL = DecimalField(max_digits=10, decimal_places=2)
    ZERO = Value(0, output_field=DECIMAL)
    fee_expr = ExpressionWrapper(F("hours") * F("rate"), output_field=DECIMAL)

    matters = (
        Matter.objects.filter(billable=True).select_related("client").order_by("name")
    )

    if status_filter and status_filter != "All":
        matters = matters.filter(status=status_filter)

    # Bulk aggregation: time entries per matter
    time_agg = (
        TimeEntry.objects.filter(matter__in=matters)
        .values("matter__id")
        .annotate(
            total_hours=Coalesce(Sum("hours"), ZERO, output_field=DECIMAL),
            total_fees=Coalesce(Sum(fee_expr), ZERO, output_field=DECIMAL),
        )
    )
    time_lookup = {
        row["matter__id"]: {
            "hours": row["total_hours"],
            "fees": row["total_fees"],
        }
        for row in time_agg
    }

    # Bulk aggregation: expenses per matter
    expense_agg = (
        ExpenseEntry.objects.filter(matter__in=matters)
        .values("matter__id")
        .annotate(
            total_expenses=Coalesce(Sum("amount"), ZERO, output_field=DECIMAL),
        )
    )
    expense_lookup = {row["matter__id"]: row["total_expenses"] for row in expense_agg}

    # Bulk aggregation: unbilled WIP per matter
    unbilled_time_agg = (
        TimeEntry.objects.filter(
            matter__in=matters, invoice__isnull=True, entered=False
        )
        .values("matter__id")
        .annotate(
            unbilled_fees=Coalesce(Sum(fee_expr), ZERO, output_field=DECIMAL),
        )
    )
    unbilled_time_lookup = {
        row["matter__id"]: row["unbilled_fees"] for row in unbilled_time_agg
    }

    unbilled_expense_agg = (
        ExpenseEntry.objects.filter(
            matter__in=matters, invoice__isnull=True, entered=False
        )
        .values("matter__id")
        .annotate(
            unbilled_expenses=Coalesce(Sum("amount"), ZERO, output_field=DECIMAL),
        )
    )
    unbilled_expense_lookup = {
        row["matter__id"]: row["unbilled_expenses"] for row in unbilled_expense_agg
    }

    # Bulk aggregation: payments per matter
    payment_agg = (
        Payment.objects.filter(matter__in=matters)
        .values("matter__id")
        .annotate(
            total_payments=Coalesce(Sum("amount"), ZERO, output_field=DECIMAL),
        )
    )
    payment_lookup = {row["matter__id"]: row["total_payments"] for row in payment_agg}

    # Bulk aggregation: invoiced amounts per matter (SENT + PAID invoices)
    invoice_time_agg = (
        TimeEntry.objects.filter(
            invoice__isnull=False,
            invoice__status__in=["SENT", "PAID"],
            invoice__matter__in=matters,
            comp=False,
        )
        .values("invoice__matter__id")
        .annotate(
            invoiced_fees=Coalesce(Sum(fee_expr), ZERO, output_field=DECIMAL),
        )
    )
    invoiced_fees_lookup = {
        row["invoice__matter__id"]: row["invoiced_fees"] for row in invoice_time_agg
    }

    invoice_expense_agg = (
        ExpenseEntry.objects.filter(
            invoice__isnull=False,
            invoice__status__in=["SENT", "PAID"],
            invoice__matter__in=matters,
            comp=False,
        )
        .values("invoice__matter__id")
        .annotate(
            invoiced_expenses=Coalesce(Sum("amount"), ZERO, output_field=DECIMAL),
        )
    )
    invoiced_expenses_lookup = {
        row["invoice__matter__id"]: row["invoiced_expenses"]
        for row in invoice_expense_agg
    }

    # Invoice discounts
    invoice_discount_agg = (
        Invoice.objects.filter(matter__in=matters, status__in=["SENT", "PAID"])
        .values("matter__id")
        .annotate(
            total_discount=Coalesce(Sum("discount"), ZERO, output_field=DECIMAL),
        )
    )
    discount_lookup = {
        row["matter__id"]: row["total_discount"] for row in invoice_discount_agg
    }

    results = []
    for matter in matters:
        time_data = time_lookup.get(matter.id, {"hours": 0, "fees": 0})
        expenses = expense_lookup.get(matter.id, 0)
        unbilled_wip = unbilled_time_lookup.get(
            matter.id, 0
        ) + unbilled_expense_lookup.get(matter.id, 0)
        payments = payment_lookup.get(matter.id, 0)
        invoiced = (
            invoiced_fees_lookup.get(matter.id, 0)
            + invoiced_expenses_lookup.get(matter.id, 0)
            - discount_lookup.get(matter.id, 0)
        )
        outstanding = invoiced - payments

        results.append(
            {
                "matter": matter,
                "matter_name": matter.name or "Unknown",
                "client_name": matter.client.name if matter.client else "",
                "total_hours": time_data["hours"],
                "total_fees": time_data["fees"],
                "total_expenses": expenses,
                "amount_invoiced": invoiced,
                "payments_received": payments,
                "outstanding": outstanding,
                "unbilled_wip": unbilled_wip,
            }
        )

    # Calculate totals
    totals = {
        "total_hours": sum(r["total_hours"] for r in results),
        "total_fees": sum(r["total_fees"] for r in results),
        "total_expenses": sum(r["total_expenses"] for r in results),
        "amount_invoiced": sum(r["amount_invoiced"] for r in results),
        "payments_received": sum(r["payments_received"] for r in results),
        "outstanding": sum(r["outstanding"] for r in results),
        "unbilled_wip": sum(r["unbilled_wip"] for r in results),
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
def matters_index(request):
    sort_by = request.GET.get("sort", "matter_name")
    sort_direction = request.GET.get("direction", "asc")
    filter_data = request.session.get("matters_filter", {})
    status_filter = filter_data.get("status", "Open")
    matter_data, totals = _get_matter_data(status_filter, sort_by, sort_direction)

    context = {
        "app": "reports",
        "subapp": "matters",
        "matter_data": matter_data,
        "totals": totals,
        "current_sort": sort_by,
        "current_direction": sort_direction,
        "status_filter": status_filter,
    }
    return render(request, "reports/matters/main.html", context)


@login_required
@staff_member_required
def matters_list(request):
    sort_by = request.GET.get("sort", "matter_name")
    sort_direction = request.GET.get("direction", "asc")
    filter_data = request.session.get("matters_filter", {})
    status_filter = filter_data.get("status", "Open")
    matter_data, totals = _get_matter_data(status_filter, sort_by, sort_direction)

    context = {
        "app": "reports",
        "subapp": "matters",
        "matter_data": matter_data,
        "totals": totals,
        "current_sort": sort_by,
        "current_direction": sort_direction,
        "status_filter": status_filter,
    }
    return render(request, "reports/matters/list.html", context)


@login_required
@staff_member_required
def matters_filter(request):
    filter_manager = FilterManager(request, MatterSummaryFilter, "matters_filter")

    if filter_manager.process_filter():
        return HttpResponse(status=204, headers={"HX-Trigger": "mattersChanged"})

    filter_data = request.session.get("matters_filter", {})

    return render(request, "reports/matters/filter.html", {"filter_data": filter_data})
