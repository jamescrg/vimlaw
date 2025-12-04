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
from apps.invoicing.credits.models import Credit
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment
from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter


def get_collection_data(request):
    """Get matters with collection data using optimized subqueries."""

    # Subquery to calculate net fees for an invoice (excluding comp'd entries)
    invoice_fees_subquery = (
        TimeEntry.objects.filter(invoice=OuterRef("pk"))
        .exclude(comp=True)
        .values("invoice")
        .annotate(total=Sum(F("hours") * F("rate"), output_field=DecimalField()))
        .values("total")
    )

    # Subquery to calculate net expenses for an invoice (excluding comp'd entries)
    invoice_expenses_subquery = (
        ExpenseEntry.objects.filter(invoice=OuterRef("pk"))
        .exclude(comp=True)
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

    # Subquery to get total billed for a matter (all invoices except DRAFT/APPROVED)
    billed_subquery = (
        invoices_with_totals.filter(matter=OuterRef("pk"))
        .exclude(status__in=["DRAFT", "APPROVED"])
        .values("matter")
        .annotate(total=Sum("final_total"))
        .values("total")
    )

    # Subquery to get total deferred for a matter (sum of DEFERRED invoice final_totals)
    deferred_subquery = (
        invoices_with_totals.filter(matter=OuterRef("pk"), status="DEFERRED")
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

    # Subquery to get total credits for a matter
    credits_subquery = (
        Credit.objects.filter(matter=OuterRef("pk"))
        .values("matter")
        .annotate(total=Sum("amount"))
        .values("total")
    )

    # Annotate matters with billed, paid, deferred, credits, and due amounts
    matters = (
        Matter.objects.annotate(
            billed=Coalesce(
                Subquery(billed_subquery, output_field=DecimalField()),
                0,
                output_field=DecimalField(),
            ),
            deferred=Coalesce(
                Subquery(deferred_subquery, output_field=DecimalField()),
                0,
                output_field=DecimalField(),
            ),
            paid=Coalesce(
                Subquery(paid_subquery, output_field=DecimalField()),
                0,
                output_field=DecimalField(),
            ),
            credits=Coalesce(
                Subquery(credits_subquery, output_field=DecimalField()),
                0,
                output_field=DecimalField(),
            ),
            balance_due=ExpressionWrapper(
                F("billed") - F("paid") - F("credits"),
                output_field=DecimalField(),
            ),
            due_after_deferrals=ExpressionWrapper(
                F("billed") - F("paid") - F("deferred") - F("credits"),
                output_field=DecimalField(),
            ),
        )
        .filter(balance_due__gt=0)
        .order_by("-due_after_deferrals")
    )

    # Convert to list for pagination
    matters_list = list(matters)

    # Calculate total due after deferrals
    total_due_after_deferrals = sum(
        matter.due_after_deferrals for matter in matters_list
    )

    pagination = CustomPaginator(
        matters_list, per_page=10, request=request, session_key="collection_pagination"
    )

    context = {
        "matters": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "collection_pagination",
        "trigger_key": "collectionChanged",
        "total_due_after_deferrals": total_due_after_deferrals,
    }

    return context
