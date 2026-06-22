from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import (
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
)
from django.db.models.functions import Coalesce
from django.shortcuts import render

from apps.accounts.access import filter_matters_for_user
from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.calendar.models import Event
from apps.intakes.models import Intake
from apps.invoicing.credits.models import Credit
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment
from apps.matters.models import Matter
from apps.reports.wip.aggregation import wip_matter_donut, wip_user_breakdown
from apps.trust.trust import get_confirmed_client_balance


def _nth_working_day(start, count):
    """Date of the `count`-th working day (Mon–Fri) on or after `start`."""
    day = start
    seen = 0
    while True:
        if day.weekday() < 5:
            seen += 1
            if seen == count:
                return day
        day += timedelta(days=1)


@login_required
def dash_index(request):
    today = date.today()

    # Upcoming events: pending events from today through the 3rd working day
    # (weekends in between still show). The table is hidden when empty.
    window_end = _nth_working_day(today, 3)
    upcoming_events = Event.objects.filter(
        status="Pending", date__gte=today, date__lte=window_end
    ).order_by("date", "start_time", "party")

    # Reporting access sees the full all-users section (identical to the WIP
    # report); everyone else sees only their own WIP. `?view=user` lets a
    # privileged user preview the regular-user view.
    wip_show_all = (request.user.is_admin or request.user.perm_reports) and (
        request.GET.get("view") != "user"
    )
    wip_self_donut = None
    if wip_show_all:
        wip_user_rows, wip_user_donut, wip_totals = wip_user_breakdown()
    else:
        wip_user_rows, wip_user_donut, wip_totals = wip_user_breakdown(
            user=request.user
        )
        # The user's own unbilled WIP by matter (top 5 + Other), shown as net.
        wip_self_donut = wip_matter_donut(request.user, top_n=5)

    # Matters with low clearance (< $1000)
    # Use subqueries to calculate unbilled amounts
    unbilled_fees_subquery = (
        TimeEntry.objects.filter(
            matter=OuterRef("pk"),
            entered=False,
            invoice__isnull=True,
        )
        .exclude(comp=True)
        .values("matter")
        .annotate(total=Sum(F("hours") * F("rate")))
        .values("total")
    )

    unbilled_expenses_subquery = (
        ExpenseEntry.objects.filter(
            matter=OuterRef("pk"),
            entered=False,
            invoice__isnull=True,
        )
        .exclude(comp=True)
        .values("matter")
        .annotate(total=Sum("amount"))
        .values("total")
    )

    # Get matters with unbilled activity
    matters_with_unbilled = (
        filter_matters_for_user(
            Matter.objects.filter(status="Open", billable=True), request.user
        )
        .annotate(
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
        .filter(Q(unbilled_fees__gt=0) | Q(unbilled_expenses__gt=0))
    )

    # Convert to list and calculate clearance
    low_clearance_matters = []
    client_trust_balances = {}

    for matter in matters_with_unbilled:
        # Get trust balance for this matter's client (cached by client)
        if matter.client:
            if matter.client.id not in client_trust_balances:
                try:
                    client_trust_balances[matter.client.id] = (
                        get_confirmed_client_balance(matter.client.id)
                    )
                except Exception:
                    client_trust_balances[matter.client.id] = 0

            trust_balance = client_trust_balances[matter.client.id]
            total_activity = matter.unbilled_fees + matter.unbilled_expenses

            # Calculate clearance (only if there's a trust balance)
            if trust_balance > 0:
                clearance = trust_balance - total_activity
                if clearance < 1000:
                    matter.clearance = clearance
                    matter.trust_balance = trust_balance
                    matter.total_activity = total_activity
                    low_clearance_matters.append(matter)

    # Sort by clearance ascending (lowest first)
    low_clearance_matters.sort(key=lambda m: m.clearance)
    low_clearance_matters = low_clearance_matters[:10]

    # Matters with outstanding balance due (excluding deferred)
    # Use subqueries to calculate at database level (avoid N+1)

    # Subquery for invoice fees (excluding comp'd entries)
    invoice_fees_subquery = (
        TimeEntry.objects.filter(invoice=OuterRef("pk"))
        .exclude(comp=True)
        .values("invoice")
        .annotate(total=Sum(F("hours") * F("rate"), output_field=DecimalField()))
        .values("total")
    )

    # Subquery for invoice expenses (excluding comp'd entries)
    invoice_expenses_subquery = (
        ExpenseEntry.objects.filter(invoice=OuterRef("pk"))
        .exclude(comp=True)
        .values("invoice")
        .annotate(total=Sum("amount"))
        .values("total")
    )

    # Annotate invoices with their final_total
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

    # Subquery for total billed (all invoices except DRAFT/APPROVED)
    billed_subquery = (
        invoices_with_totals.filter(matter=OuterRef("pk"))
        .exclude(status__in=["DRAFT", "APPROVED", "VOID"])
        .values("matter")
        .annotate(total=Sum("final_total"))
        .values("total")
    )

    # Subquery for deferred invoice totals
    deferred_subquery = (
        invoices_with_totals.filter(matter=OuterRef("pk"), status="DEFERRED")
        .values("matter")
        .annotate(total=Sum("final_total"))
        .values("total")
    )

    # Subquery for total payments
    paid_subquery = (
        Payment.objects.filter(matter=OuterRef("pk"))
        .values("matter")
        .annotate(total=Sum("amount"))
        .values("total")
    )

    # Subquery for total credits
    credits_subquery = (
        Credit.objects.filter(matter=OuterRef("pk"))
        .values("matter")
        .annotate(total=Sum("amount"))
        .values("total")
    )

    # Annotate matters and filter for positive balance due
    balance_due_matters = list(
        filter_matters_for_user(Matter.objects.filter(billable=True), request.user)
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
            balance_due=ExpressionWrapper(
                F("billed") - F("paid") - F("deferred") - F("credits"),
                output_field=DecimalField(),
            ),
        )
        .filter(balance_due__gt=0)
        .order_by("-balance_due")[:10]
    )

    # Open intakes
    open_intakes = Intake.objects.filter(status="Open").order_by("-date")[:10]

    context = {
        "app": "dash",
        "upcoming_events": upcoming_events,
        "wip_show_all": wip_show_all,
        "wip_heading": "Unbilled Time",
        "user_rows": wip_user_rows,
        "user_donut": wip_user_donut,
        "user_self_donut": wip_self_donut,
        "totals": wip_totals,
        "low_clearance_matters": low_clearance_matters,
        "balance_due_matters": balance_due_matters,
        "open_intakes": open_intakes,
        "today": today,
    }

    return render(request, "dash/dash.html", context)
