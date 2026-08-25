"""Realization report aggregation — collection performance on accrued FEES.

For every billable hour accrued (dated) in a month, this traces the standard fee
value (hours × rate) to its ultimate disposition, so each month's bar reconciles
to 100% of the fees worked that month and "Collected ÷ bar" is the realization
rate.

Fees only: expenses are excluded entirely (this measures performance collecting
billed *hours*, not cost pass-throughs). Flat fees are shown as a separate band
(accrued value), kept out of the hourly disposition so Deferred stays the genuine
hourly-deferred and the realization rate is hourly-only. Comp time and the
fee-share of any invoice discount are write-downs; payments and credits are
pro-rated back to each entry's accrual month by the entry's share of its
invoice's net billable value (the same engine the Revenue report uses).

Non-billable matters (internal/admin, ``matter.billable=False``) are excluded
entirely, matching the Activity report — their tracked time is never meant to be
collected and shouldn't drag the realization rate down.

Accrual basis: a month column counts time entries by their own ``date``. The
window's end month is held in the session ("realization_end") and stepped by
``realization_period``.
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db.models import DecimalField, F, Sum
from django.utils import timezone

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.flat_fees.models import FlatFeeEntry
from apps.activity.time.models import TimeEntry
from apps.invoicing.applications.models import CreditApplication, PaymentApplication
from apps.invoicing.invoices.models import Invoice
from apps.reports.activity.aggregation import _window_months


def resolve_realization_end(session_value):
    """Resolve the window's end month, but the latest selectable month is the
    PREVIOUS (completed) month: the current month has barely any realization yet
    (no time to collect) and would skew the trend toward 0%. Returns
    (end_first_of_month, latest_complete_first_of_month)."""
    latest = timezone.localdate().replace(day=1) - relativedelta(months=1)
    try:
        year, month = (int(part) for part in session_value.split("-"))
        end = date(year, month, 1)
    except (AttributeError, TypeError, ValueError):
        end = latest
    return min(end, latest), latest


# Disposition segments, bottom-of-stack first. Each accrued fee dollar lands in
# exactly one, so the stack reconciles to the month's accrued fee value.
COLLECTED = "Collected"
CREDITS = "Credits applied"
OUTSTANDING = "Outstanding"
DEFERRED = "Deferred"
UNCOLLECTIBLE = "Uncollectible"
WRITEDOWNS = "Write-downs (comp & discount)"
UNBILLED = "Unbilled (WIP)"
# Flat fees are shown as their own band (accrued value), deliberately kept out of
# the hourly disposition — Deferred stays the genuine hourly-deferred. The
# realization rate is computed on hourly fees only.
FLATFEES = "Flat fees"
SEGMENTS = [
    COLLECTED,
    CREDITS,
    OUTSTANDING,
    DEFERRED,
    UNCOLLECTIBLE,
    WRITEDOWNS,
    UNBILLED,
    FLATFEES,
]
NEUTRAL = {UNBILLED}  # rendered grey on the chart


def _net_map(model, value_expr, invoice_ids):
    """{invoice_id: Σ non-comp value} for a line-item model."""
    out = defaultdict(lambda: Decimal(0))
    rows = (
        model.objects.filter(invoice_id__in=invoice_ids, comp=False)
        .values("invoice_id")
        .annotate(
            net=Sum(
                value_expr, output_field=DecimalField(max_digits=12, decimal_places=2)
            )
        )
    )
    for r in rows:
        out[r["invoice_id"]] = Decimal(r["net"] or 0)
    return out


def _applied_map(model, invoice_ids):
    out = defaultdict(lambda: Decimal(0))
    rows = (
        model.objects.filter(invoice_id__in=invoice_ids)
        .values("invoice_id")
        .annotate(s=Sum("amount_applied"))
    )
    for r in rows:
        out[r["invoice_id"]] = Decimal(r["s"] or 0)
    return out


def _invoice_facts(invoice_ids):
    """Per-invoice disposition facts used to split each billed fee entry.

    Returns {invoice_id: {net, discount, collected, credited, remainder,
    remainder_seg}} where the amounts are the whole-invoice figures (fees +
    expenses + flat fees); callers pro-rate by each entry's fee share of ``net``.
    """
    if not invoice_ids:
        return {}

    fees = _net_map(TimeEntry, F("hours") * F("rate"), invoice_ids)
    exps = _net_map(ExpenseEntry, F("amount"), invoice_ids)
    flats = _net_map(FlatFeeEntry, F("amount"), invoice_ids)
    pay = _applied_map(PaymentApplication, invoice_ids)
    cred = _applied_map(CreditApplication, invoice_ids)
    status_map = {
        r["id"]: (r["status"], Decimal(r["discount"] or 0))
        for r in Invoice.objects.filter(id__in=invoice_ids).values(
            "id", "status", "discount"
        )
    }

    facts = {}
    for iid in invoice_ids:
        net = fees[iid] + exps[iid] + flats[iid]
        if net <= 0:
            facts[iid] = {"net": Decimal(0)}
            continue
        status, discount = status_map.get(iid, ("", Decimal(0)))
        discount = min(max(discount, Decimal(0)), net)
        final = net - discount
        collected = pay[iid]
        credited = cred[iid]
        paid = collected + credited
        # Clamp overpayment (e.g. a duplicated charge) so segments stay >= 0.
        if paid > final and paid > 0:
            scale = final / paid
            collected *= scale
            credited *= scale
        remainder = final - collected - credited
        if remainder < 0:
            remainder = Decimal(0)
        if status == "DEFERRED":
            seg = DEFERRED
        elif status == "UNCOLLECTIBLE":
            seg = UNCOLLECTIBLE
        elif status == "VOID":
            seg = UNBILLED  # void releases its entries; should not occur here
        else:
            seg = OUTSTANDING
        facts[iid] = {
            "net": net,
            "discount": discount,
            "collected": collected,
            "credited": credited,
            "remainder": remainder,
            "remainder_seg": seg,
        }
    return facts


def build_realization_context(request):
    """Full template context for the realization report, incl. ``chart_payload``."""
    end, latest = resolve_realization_end(request.session.get("realization_end"))
    months = _window_months(end)
    n = len(months)
    window_start = months[0]["date"]
    window_end = months[-1]["date"] + relativedelta(months=1)
    month_index = {(m["year"], m["month"]): i for i, m in enumerate(months)}

    buckets = {seg: [Decimal(0)] * n for seg in SEGMENTS}

    entries = list(
        TimeEntry.objects.filter(
            date__gte=window_start, date__lt=window_end, matter__billable=True
        ).values("date", "hours", "rate", "comp", "invoice_id")
    )
    invoice_ids = {
        e["invoice_id"] for e in entries if not e["comp"] and e["invoice_id"]
    }
    facts = _invoice_facts(invoice_ids)

    for e in entries:
        fee = Decimal(e["hours"] or 0) * Decimal(e["rate"] or 0)
        if fee <= 0:
            continue
        idx = month_index[(e["date"].year, e["date"].month)]

        if e["comp"]:
            buckets[WRITEDOWNS][idx] += fee
            continue
        if not e["invoice_id"]:
            buckets[UNBILLED][idx] += fee
            continue
        f = facts.get(e["invoice_id"])
        if not f or f["net"] <= 0:
            buckets[UNBILLED][idx] += fee  # fallback; shouldn't occur
            continue

        share = fee / f["net"]
        buckets[WRITEDOWNS][idx] += f["discount"] * share
        buckets[COLLECTED][idx] += f["collected"] * share
        buckets[CREDITS][idx] += f["credited"] * share
        buckets[f["remainder_seg"]][idx] += f["remainder"] * share

    # Flat fees: their own band (accrued value), kept out of the hourly
    # disposition. Comp (no-charge) flat fees are write-downs, like comp time.
    flat_entries = list(
        FlatFeeEntry.objects.filter(
            date__gte=window_start, date__lt=window_end, matter__billable=True
        ).values("date", "amount", "comp")
    )
    for fe in flat_entries:
        amt = Decimal(fe["amount"] or 0)
        if amt <= 0 or not fe["date"]:
            continue
        idx = month_index[(fe["date"].year, fe["date"].month)]
        buckets[WRITEDOWNS if fe["comp"] else FLATFEES][idx] += amt

    # Table rows (skip wholly-empty segments) + per-month and grand totals.
    month_totals = [Decimal(0)] * n
    grand_total = Decimal(0)
    rows = []
    for seg in SEGMENTS:
        data = buckets[seg]
        row_total = sum(data, Decimal(0))
        for i in range(n):
            month_totals[i] += data[i]
        grand_total += row_total
        if row_total == 0:
            continue
        rows.append(
            {"label": seg, "cells": [{"amount": v} for v in data], "total": row_total}
        )

    for row in rows:
        row["pct"] = (row["total"] / grand_total * 100) if grand_total else Decimal(0)
        for i, cell in enumerate(row["cells"]):
            mt = month_totals[i]
            cell["pct"] = (cell["amount"] / mt * 100) if mt else Decimal(0)

    # Realization rate = Collected ÷ accrued HOURLY fees (flat fees are a separate
    # band, excluded from the denominator), per month and overall.
    collected = buckets[COLLECTED]
    flat = buckets[FLATFEES]
    hourly_totals = [month_totals[i] - flat[i] for i in range(n)]
    realization_cells = [
        {
            "pct": (collected[i] / hourly_totals[i] * 100)
            if hourly_totals[i]
            else Decimal(0)
        }
        for i in range(n)
    ]
    hourly_grand = sum(hourly_totals, Decimal(0))
    overall_realization = (
        sum(collected, Decimal(0)) / hourly_grand * 100 if hourly_grand else Decimal(0)
    )

    # Chart: one stacked series per non-empty segment; WIP renders grey.
    series = []
    for seg in SEGMENTS:
        data = buckets[seg]
        if sum(data, Decimal(0)) == 0:
            continue
        s = {"label": seg, "fees": [float(round(v, 2)) for v in data]}
        if seg in NEUTRAL:
            s["neutral"] = True
        series.append(s)
    chart_payload = {
        "months": [m["name"] for m in months],
        "series": {"segment": series},
        # Per-bar top label: the month's hourly realization rate (blank when no
        # hourly fees accrued that month).
        "top_labels": [
            f"{realization_cells[i]['pct']:.1f}%" if hourly_totals[i] else ""
            for i in range(n)
        ],
    }

    if settings.DEBUG:
        accrued_hourly = sum(
            (
                Decimal(e["hours"] or 0) * Decimal(e["rate"] or 0)
                for e in entries
                if Decimal(e["hours"] or 0) * Decimal(e["rate"] or 0) > 0
            ),
            Decimal(0),
        )
        accrued_flat = sum(
            (
                Decimal(fe["amount"] or 0)
                for fe in flat_entries
                if fe["amount"] and fe["date"]
            ),
            Decimal(0),
        )
        accrued = accrued_hourly + accrued_flat
        assert abs(grand_total - accrued) < Decimal("0.01"), (
            f"realization mismatch: {grand_total} != {accrued}"
        )

    return {
        "app": "reports",
        "subapp": "realization",
        "months": months,
        "realization_rows": rows,
        "month_totals": [{"amount": v} for v in month_totals],
        "grand_total": grand_total,
        "collected_cells": [{"amount": v} for v in collected],
        "collected_total": sum(collected, Decimal(0)),
        "realization_cells": realization_cells,
        "overall_realization": overall_realization,
        "period_label": end.strftime("%b %Y"),
        "can_go_next": end < latest,
        "chart_payload": chart_payload,
    }
