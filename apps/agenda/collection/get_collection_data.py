from django.db.models import (
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Subquery,
    Sum,
)
from django.db.models.functions import Coalesce

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment
from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter


def get_collection_data(request):
    """Get matters with collection data using optimized subqueries."""

    # Subquery to calculate net fees for an invoice (excluding comp'd entries)
    invoice_fees_subquery = (
        TimeEntry.objects.filter(invoice=OuterRef("pk"))
        .exclude(comp=1)
        .values("invoice")
        .annotate(total=Sum(F("hours") * F("rate"), output_field=DecimalField()))
        .values("total")
    )

    # Subquery to calculate net expenses for an invoice (excluding comp'd entries)
    invoice_expenses_subquery = (
        ExpenseEntry.objects.filter(invoice=OuterRef("pk"))
        .exclude(comp=1)
        .values("invoice")
        .annotate(total=Sum("amount"))
        .values("total")
    )

    # Annotate invoices with their final_total (net_fees + net_expenses - discount)
    invoices_with_totals = Invoice.objects.annotate(
        net_fees=Coalesce(
            Subquery(invoice_fees_subquery, output_field=DecimalField()), 0
        ),
        net_expenses=Coalesce(
            Subquery(invoice_expenses_subquery, output_field=DecimalField()), 0
        ),
        final_total=ExpressionWrapper(
            F("net_fees") + F("net_expenses") - F("discount"),
            output_field=DecimalField(),
        ),
    )

    # Subquery to get total billed for a matter (sum of SENT/PAID invoice final_totals)
    billed_subquery = (
        invoices_with_totals.filter(matter=OuterRef("pk"), status__in=["SENT", "PAID"])
        .values("matter")
        .annotate(total=Sum("final_total"))
        .values("total")
    )

    # Subquery to get total paid for a matter
    paid_subquery = (
        Payment.objects.filter(matter=OuterRef("pk"))
        .values("matter")
        .annotate(total=Sum("amount"))
        .values("total")
    )

    # Annotate matters with billed, paid, and due amounts
    matters = (
        Matter.objects.filter(status__in=["Pending", "Open", "Complete"])
        .annotate(
            billed=Coalesce(
                Subquery(billed_subquery, output_field=DecimalField()),
                0,
                output_field=DecimalField(),
            ),
            paid=Coalesce(
                Subquery(paid_subquery, output_field=DecimalField()),
                0,
                output_field=DecimalField(),
            ),
            due=ExpressionWrapper(F("billed") - F("paid"), output_field=DecimalField()),
        )
        .filter(due__gt=0)
        .order_by("-due")
    )

    # Convert to list for pagination
    matters_list = list(matters)

    # Calculate total due
    total_due = sum(matter.due for matter in matters_list)

    pagination = CustomPaginator(
        matters_list, per_page=10, request=request, session_key="collection_pagination"
    )

    context = {
        "matters": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "collection_pagination",
        "trigger_key": "collectionChanged",
        "total_due": total_due,
    }

    return context
