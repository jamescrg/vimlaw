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

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.agenda.events.models import Event
from apps.agenda.tasks.models import Task
from apps.intakes.models import Intake
from apps.invoicing.credits.models import Credit
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment
from apps.matters.models import Matter
from apps.trust.trust import get_confirmed_client_balance


@login_required
def dash_index(request):
    today = date.today()
    tomorrow = today + timedelta(days=1)

    # All pending events ordered by date (captures past due and upcoming)
    upcoming_events = Event.objects.filter(status="Pending").order_by("date", "party")[
        :4
    ]

    # Count of events in the next 7 days for the summary
    end_date = today + timedelta(days=7)
    events_next_7_days_count = Event.objects.filter(
        date__gte=today, date__lte=end_date
    ).count()

    # Tasks past due, due today, or due tomorrow, ordered by due date then priority
    urgent_tasks = Task.objects.filter(
        status="Pending",
        date_due__lte=tomorrow,
    ).order_by("date_due", "priority")

    # Unbilled hours and fees by user
    unbilled_by_user = (
        TimeEntry.objects.filter(
            entered=False,
            invoice__isnull=True,
        )
        .exclude(comp=True)
        .values("user__username")
        .annotate(
            total_hours=Coalesce(Sum("hours"), 0, output_field=DecimalField()),
            total_fees=Coalesce(
                Sum(F("hours") * F("rate")), 0, output_field=DecimalField()
            ),
        )
        .order_by("user__username")
    )

    # Calculate totals for unbilled
    unbilled_total_hours = sum(entry["total_hours"] for entry in unbilled_by_user)
    unbilled_total_fees = sum(entry["total_fees"] for entry in unbilled_by_user)

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
        Matter.objects.filter(status="Open")
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
        .exclude(status__in=["DRAFT", "APPROVED"])
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
        "app": "agenda",
        "subapp": "dash",
        "upcoming_events": upcoming_events,
        "upcoming_events_count": len(upcoming_events),
        "events_next_7_days_count": events_next_7_days_count,
        "urgent_tasks": urgent_tasks,
        "unbilled_by_user": unbilled_by_user,
        "unbilled_total_hours": unbilled_total_hours,
        "unbilled_total_fees": unbilled_total_fees,
        "low_clearance_matters": low_clearance_matters,
        "balance_due_matters": balance_due_matters,
        "open_intakes": open_intakes,
        "today": today,
        "tomorrow": tomorrow,
    }

    return render(request, "agenda/dash/dash.html", context)
