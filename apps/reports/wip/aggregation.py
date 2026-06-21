"""Unbilled WIP aggregation — a current snapshot of billable, un-invoiced time.

WIP here is time only: `TimeEntry` rows on billable matters that are not yet on
an invoice and not yet entered. Each row's value is `hours * rate`, split into
gross (all of it), comp (the written-off portion) and net (gross − comp, the
billable WIP). `build_wip_context` groups this by user and by matter for the
two donut charts + tables. It's a snapshot — no date window.
"""

from decimal import Decimal

from django.conf import settings
from django.db.models import (
    Case,
    DecimalField,
    ExpressionWrapper,
    F,
    Sum,
    Value,
    When,
)

from apps.activity.time.models import TimeEntry

# Matters charted before the rest roll up into a single "Other" donut slice.
TOP_MATTERS = 8

_DECIMAL = DecimalField(max_digits=12, decimal_places=2)
_FEE = ExpressionWrapper(F("hours") * F("rate"), output_field=_DECIMAL)
_COMP_FEE = Case(
    When(comp=True, then=_FEE),
    default=Value(0),
    output_field=_DECIMAL,
)


def _d(value):
    return Decimal(value or 0)


def _money(value):
    return round(float(value or 0), 2)


def _row(label, group):
    """Turn a grouped aggregate row into a table/series row with net + pct gap."""
    gross = _d(group["gross"])
    comp = _d(group["comp"])
    return {
        "label": label,
        "hours": _d(group["hours_sum"]),
        "gross": gross,
        "comp": comp,
        "net": gross - comp,
    }


def build_wip_context(request):
    """Full template context for the WIP report, including donut payloads."""
    base = TimeEntry.objects.filter(
        invoice__isnull=True, entered=False, matter__billable=True
    )

    by_user = base.values(
        "user_id", "user__first_name", "user__last_name", "user__username"
    ).annotate(hours_sum=Sum("hours"), gross=Sum(_FEE), comp=Sum(_COMP_FEE))

    by_matter = base.values(
        "matter_id", "matter__name", "matter__client__name"
    ).annotate(hours_sum=Sum("hours"), gross=Sum(_FEE), comp=Sum(_COMP_FEE))

    # --- by user ---
    user_rows = []
    for g in by_user:
        name = f"{g['user__first_name']} {g['user__last_name']}".strip()
        label = name or g["user__username"] or "Unassigned"
        user_rows.append(_row(label, g))
    user_rows.sort(key=lambda r: r["net"], reverse=True)

    # --- by matter ---
    matter_rows = []
    for g in by_matter:
        matter_rows.append(
            {
                **_row(g["matter__name"] or "Unknown", g),
                "matter_id": g["matter_id"],
                "client": g["matter__client__name"] or "",
            }
        )
    matter_rows.sort(key=lambda r: r["net"], reverse=True)

    totals = {
        "hours": sum((r["hours"] for r in user_rows), Decimal(0)),
        "gross": sum((r["gross"] for r in user_rows), Decimal(0)),
        "comp": sum((r["comp"] for r in user_rows), Decimal(0)),
        "net": sum((r["net"] for r in user_rows), Decimal(0)),
    }
    total_net = totals["net"]
    for rows in (user_rows, matter_rows):
        for r in rows:
            r["pct"] = (r["net"] / total_net * 100) if total_net else Decimal(0)

    if settings.DEBUG:
        matter_net = sum((r["net"] for r in matter_rows), Decimal(0))
        assert matter_net == total_net, f"WIP net mismatch: {matter_net} != {total_net}"

    user_donut = _donut(user_rows, cap=False)
    matter_donut = _donut(matter_rows, cap=True)

    return {
        "app": "reports",
        "subapp": "wip",
        "user_rows": user_rows,
        "matter_rows": matter_rows,
        "totals": totals,
        "user_donut": user_donut,
        "matter_donut": matter_donut,
    }


def _donut(rows, cap):
    """Build a donut payload from rows. When `cap`, keep the top TOP_MATTERS by
    gross and fold the rest into a trailing neutral "Other" slice."""
    ranked = sorted(rows, key=lambda r: r["gross"], reverse=True)
    has_other = cap and len(ranked) > TOP_MATTERS
    head = ranked[:TOP_MATTERS] if cap else ranked

    labels = [r["label"] for r in head]
    gross = [_money(r["gross"]) for r in head]
    net = [_money(r["net"]) for r in head]
    comp = [_money(r["comp"]) for r in head]

    if has_other:
        rest = ranked[TOP_MATTERS:]
        labels.append("Other")
        gross.append(_money(sum((r["gross"] for r in rest), Decimal(0))))
        net.append(_money(sum((r["net"] for r in rest), Decimal(0))))
        comp.append(_money(sum((r["comp"] for r in rest), Decimal(0))))

    return {
        "labels": labels,
        "gross": gross,
        "net": net,
        "comp": comp,
        "hasOther": has_other,
    }
