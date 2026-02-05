from decimal import Decimal

from django.db.models import (
    Case,
    DecimalField,
    F,
    OuterRef,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.invoicing.applications.models import CreditApplication, PaymentApplication
from apps.invoicing.invoices.filters import InvoiceFilter
from apps.invoicing.invoices.models import INVOICE_STATUS, Invoice
from apps.management.pagination import CustomPaginator


def get_annotated_invoice_queryset():
    """
    Return Invoice queryset with pre-calculated fee, expense, and payment annotations.
    This avoids N+1 queries when accessing invoice values in templates.
    """
    # Subquery for net fees (gross - comp)
    fee_subquery = (
        TimeEntry.objects.filter(invoice=OuterRef("pk"))
        .values("invoice")
        .annotate(
            total=Sum(
                Case(
                    When(comp=False, then=F("hours") * F("rate")),
                    default=Value(0),
                    output_field=DecimalField(max_digits=10, decimal_places=2),
                )
            )
        )
        .values("total")
    )

    # Subquery for net expenses (gross - comp)
    expense_subquery = (
        ExpenseEntry.objects.filter(invoice=OuterRef("pk"))
        .values("invoice")
        .annotate(
            total=Sum(
                Case(
                    When(comp=False, then=F("amount")),
                    default=Value(0),
                    output_field=DecimalField(max_digits=10, decimal_places=2),
                )
            )
        )
        .values("total")
    )

    # Subquery for payment applications
    payment_subquery = (
        PaymentApplication.objects.filter(invoice=OuterRef("pk"))
        .values("invoice")
        .annotate(total=Sum("amount_applied"))
        .values("total")
    )

    # Subquery for credit applications
    credit_subquery = (
        CreditApplication.objects.filter(invoice=OuterRef("pk"))
        .values("invoice")
        .annotate(total=Sum("amount_applied"))
        .values("total")
    )

    return (
        Invoice.objects.annotate(
            annotated_net_fees=Coalesce(
                Subquery(fee_subquery), Decimal("0"), output_field=DecimalField()
            ),
            annotated_net_expenses=Coalesce(
                Subquery(expense_subquery), Decimal("0"), output_field=DecimalField()
            ),
            annotated_payments=Coalesce(
                Subquery(payment_subquery), Decimal("0"), output_field=DecimalField()
            ),
            annotated_credits=Coalesce(
                Subquery(credit_subquery), Decimal("0"), output_field=DecimalField()
            ),
        )
        .annotate(
            # Calculate final_total = net_fees + net_expenses - discount
            annotated_final_total=F("annotated_net_fees")
            + F("annotated_net_expenses")
            - F("discount"),
            # Calculate amount_remaining = final_total - payments - credits
            # Legacy PAID invoices without allocations are considered fully paid (0)
            annotated_amount_remaining=Case(
                When(
                    status="PAID",
                    annotated_payments=Decimal("0"),
                    annotated_credits=Decimal("0"),
                    then=Value(Decimal("0")),
                ),
                default=F("annotated_net_fees")
                + F("annotated_net_expenses")
                - F("discount")
                - F("annotated_payments")
                - F("annotated_credits"),
                output_field=DecimalField(),
            ),
        )
        .select_related("matter", "created_by")
    )


def get_invoice_data(request):
    filter_data = request.session.get("invoices_filter", {})

    # Get annotated queryset
    base_queryset = get_annotated_invoice_queryset().order_by("-created_at")

    if filter_data:
        filter = InvoiceFilter(filter_data, queryset=base_queryset)
        invoices = filter.qs
    else:
        invoices = base_queryset

    # Calculate totals using database aggregation (single query)
    totals = invoices.aggregate(
        total_fees=Coalesce(Sum("annotated_net_fees"), Decimal("0")),
        total_expenses=Coalesce(Sum("annotated_net_expenses"), Decimal("0")),
    )
    total_fees = totals["total_fees"]
    total_expenses = totals["total_expenses"]
    total = total_fees + total_expenses

    # Calculate amount due using annotations
    # For legacy PAID invoices without allocations, amount_remaining = 0
    # Otherwise: final_total - payments - credits
    # final_total = net_fees + net_expenses - discount
    total_amount_due = Decimal("0")
    for invoice in invoices:
        final_total = (
            invoice.annotated_net_fees
            + invoice.annotated_net_expenses
            - invoice.discount
        )
        paid = invoice.annotated_payments + invoice.annotated_credits
        # Legacy support: PAID invoices without allocations are fully paid
        if invoice.status == "PAID" and paid == 0:
            continue
        total_amount_due += final_total - paid

    pagination = CustomPaginator(
        invoices, per_page=20, request=request, session_key="invoices_pagination"
    )

    selected_status = filter_data.get("status", "") if filter_data else ""

    # Get current order and strip leading '-' for comparison
    current_order = (
        filter_data.get("order_by", "date_issued") if filter_data else "date_issued"
    )
    current_order = current_order.lstrip("-")

    context = {
        "pagination": pagination,
        "session_key": "invoices_pagination",
        "trigger_key": "invoicesChanged",
        "objects": pagination.get_object_list(),
        "total_fees": total_fees,
        "total_expenses": total_expenses,
        "total": total,
        "total_amount_due": total_amount_due,
        "status_options": INVOICE_STATUS,
        "selected_status": selected_status,
        "current_order": current_order,
    }

    return context
