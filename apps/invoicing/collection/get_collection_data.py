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
from apps.activity.flat_fees.models import FlatFeeEntry
from apps.activity.time.models import TimeEntry
from apps.invoicing.applications.models import CreditApplication, PaymentApplication
from apps.invoicing.invoices.models import Invoice
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

    # Subquery to calculate net flat fees for an invoice (excluding comp'd entries)
    invoice_flat_fees_subquery = (
        FlatFeeEntry.objects.filter(invoice=OuterRef("pk"))
        .exclude(comp=True)
        .values("invoice")
        .annotate(total=Sum("amount"))
        .values("total")
    )

    # Annotate invoices with their final_total (net_fees + net_expenses + net_flat_fees - discount)
    invoices_with_totals = Invoice.objects.annotate(
        net_fees=Coalesce(
            Subquery(invoice_fees_subquery, output_field=DecimalField()), 0
        ),
        net_expenses=Coalesce(
            Subquery(invoice_expenses_subquery, output_field=DecimalField()), 0
        ),
        net_flat_fees=Coalesce(
            Subquery(invoice_flat_fees_subquery, output_field=DecimalField()), 0
        ),
        final_total=ExpressionWrapper(
            F("net_fees") + F("net_expenses") + F("net_flat_fees") - F("discount"),
            output_field=DecimalField(),
        ),
    )

    # Subquery to get total billed for a matter
    # (all invoices except DRAFT/APPROVED/VOID/UNCOLLECTIBLE)
    billed_subquery = (
        invoices_with_totals.filter(matter=OuterRef("pk"))
        .exclude(status__in=["DRAFT", "APPROVED", "VOID", "UNCOLLECTIBLE"])
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

    # Total paid toward a matter. Payments are client-scoped now, so "paid for
    # this matter" is the sum of PaymentApplications to the matter's invoices —
    # unapplied funds are a client-level credit, not a matter payment.
    paid_subquery = (
        PaymentApplication.objects.filter(invoice__matter=OuterRef("pk"))
        .values("invoice__matter")
        .annotate(total=Sum("amount_applied"))
        .values("total")
    )

    # Total credits applied toward a matter (same applications-based reasoning).
    credits_subquery = (
        CreditApplication.objects.filter(invoice__matter=OuterRef("pk"))
        .values("invoice__matter")
        .annotate(total=Sum("amount_applied"))
        .values("total")
    )

    # Payments/credits already applied to this matter's DEFERRED invoices. The
    # `- deferred` term below removes deferred invoices from what's owed; without
    # adding these back, the payments applied to them would be double-counted and
    # push the due figure negative.
    paid_to_deferred_subquery = (
        PaymentApplication.objects.filter(
            invoice__matter=OuterRef("pk"), invoice__status="DEFERRED"
        )
        .values("invoice__matter")
        .annotate(total=Sum("amount_applied"))
        .values("total")
    )

    credits_to_deferred_subquery = (
        CreditApplication.objects.filter(
            invoice__matter=OuterRef("pk"), invoice__status="DEFERRED"
        )
        .values("invoice__matter")
        .annotate(total=Sum("amount_applied"))
        .values("total")
    )

    # Annotate matters with billed, paid, deferred, credits, and due amounts
    matters = (
        Matter.objects.filter(billable=True)
        .annotate(
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
            paid_to_deferred=Coalesce(
                Subquery(paid_to_deferred_subquery, output_field=DecimalField()),
                0,
                output_field=DecimalField(),
            ),
            credits_to_deferred=Coalesce(
                Subquery(credits_to_deferred_subquery, output_field=DecimalField()),
                0,
                output_field=DecimalField(),
            ),
            balance_due=ExpressionWrapper(
                F("billed") - F("paid") - F("credits"),
                output_field=DecimalField(),
            ),
            due_after_deferrals=ExpressionWrapper(
                F("billed")
                - F("paid")
                - F("deferred")
                - F("credits")
                + F("paid_to_deferred")
                + F("credits_to_deferred"),
                output_field=DecimalField(),
            ),
        )
        .filter(due_after_deferrals__gt=0)
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
