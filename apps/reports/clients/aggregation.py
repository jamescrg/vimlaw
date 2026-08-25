"""Clients report context — shared by the index/list views.

Lists actual clients (contacts that are the *primary* client of at least one
matter — so secondary contacts on someone else's matter no longer appear as
empty rows) with their hours / fees / billings / payments. Defaults to lifetime
totals (no date filter) so a clients overview isn't all zeros; the date filter
still scopes it. Also builds a top-4-clients-by-billings donut (+ "All others").
"""

from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.db.models import Sum
from django.utils import timezone

from apps.activity.time.models import TimeEntry
from apps.contacts.models import Contact
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment

TOP_N = 7

# Trailing-window options (raw N-month lookbacks, not calendar periods).
CLIENT_PERIODS = [
    ("1m", "1 Month"),
    ("3m", "3 Months"),
    ("6m", "6 Months"),
    ("12m", "12 Months"),
]
_PERIOD_MONTHS = {"1m": 1, "3m": 3, "6m": 6, "12m": 12}
DEFAULT_PERIOD = "3m"


def _period_range(period):
    """Trailing (date_min, date_max): the last N months ending today."""
    today = timezone.localdate()
    months = _PERIOD_MONTHS.get(period, _PERIOD_MONTHS[DEFAULT_PERIOD])
    return today - relativedelta(months=months), today


def build_clients_context(request):
    sort_by = request.GET.get("sort", "client_name")
    sort_direction = request.GET.get("direction", "asc")

    period = request.session.get("clients_period", DEFAULT_PERIOD)
    if period not in dict(CLIENT_PERIODS):
        period = DEFAULT_PERIOD
    date_from_obj, date_to_obj = _period_range(period)

    # Actual clients only: marked Current AND the primary client of >=1 matter.
    # (Secondary contacts on a matter are excluded — they have no billings.)
    current_clients = Contact.objects.current_clients().order_by("name")

    client_data = []
    for client in current_clients:
        time_entries = TimeEntry.objects.filter(matter__client=client)
        if date_from_obj:
            time_entries = time_entries.filter(date__gte=date_from_obj)
        if date_to_obj:
            time_entries = time_entries.filter(date__lte=date_to_obj)
        total_hours = time_entries.aggregate(Sum("hours"))["hours__sum"] or 0
        total_fees = sum(entry.fee for entry in time_entries)

        invoices = Invoice.objects.filter(
            matter__client=client, status__in=["SENT", "PAID"]
        )
        if date_from_obj:
            invoices = invoices.filter(date_issued__gte=date_from_obj)
        if date_to_obj:
            invoices = invoices.filter(date_issued__lte=date_to_obj)
        total_invoices = sum(invoice.value["final_total"] for invoice in invoices)

        payments = Payment.objects.filter(matter__client=client)
        if date_from_obj:
            payments = payments.filter(date__gte=date_from_obj)
        if date_to_obj:
            payments = payments.filter(date__lte=date_to_obj)
        total_payments = payments.aggregate(Sum("amount"))["amount__sum"] or 0

        client_data.append(
            {
                "client": client,
                "client_name": client.name,
                "total_hours": total_hours,
                "total_fees": total_fees,
                "total_invoices": total_invoices,
                "total_payments": total_payments,
                "time_entries_count": time_entries.count(),
                "invoices_count": invoices.count(),
                "payments_count": payments.count(),
            }
        )

    # Sort the table.
    reverse_sort = sort_direction == "desc"
    if sort_by == "client_name":
        client_data.sort(key=lambda x: x["client_name"].lower(), reverse=reverse_sort)
    else:
        client_data.sort(key=lambda x: x[sort_by], reverse=reverse_sort)

    # Donut: top N clients by billings, with the rest folded into "All others".
    ranked = sorted(
        client_data, key=lambda c: Decimal(c["total_invoices"] or 0), reverse=True
    )
    top = [c for c in ranked[:TOP_N] if c["total_invoices"] > 0]
    others_total = sum(
        (Decimal(c["total_invoices"] or 0) for c in ranked[len(top) :]), Decimal(0)
    )
    donut_labels = [c["client_name"] for c in top]
    donut_values = [float(round(Decimal(c["total_invoices"]), 2)) for c in top]
    if others_total > 0:
        donut_labels.append("All others")
        donut_values.append(float(round(others_total, 2)))
    clients_donut = {
        "labels": donut_labels,
        "billed": donut_values,
        "hasOther": others_total > 0,
    }

    return {
        "app": "reports",
        "subapp": "clients",
        "client_data": client_data,
        "clients_donut": clients_donut,
        "current_sort": sort_by,
        "current_direction": sort_direction,
        "client_period": period,
        "period_label": dict(CLIENT_PERIODS)[period],
        "client_periods": CLIENT_PERIODS,
    }
