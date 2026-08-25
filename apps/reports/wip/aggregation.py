"""Unbilled WIP aggregation — a current snapshot of billable, un-invoiced time.

WIP here is time only: `TimeEntry` rows on billable matters that are not yet on
an invoice and not yet entered. Each row's value is `hours * rate`, split into
gross (all of it), comp (the written-off portion) and net (gross − comp, the
billable WIP). `build_wip_context` groups this by user and by matter for the
two donut charts + tables. It's a snapshot — no date window.
"""

from datetime import timedelta
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
from django.utils import timezone

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


def _wip_base(date_min=None, date_max=None):
    qs = TimeEntry.objects.filter(
        invoice__isnull=True, entered=False, matter__billable=True
    )
    if date_min:
        qs = qs.filter(date__gte=date_min)
    if date_max:
        qs = qs.filter(date__lte=date_max)
    return qs


# Quick-filter periods for the dashboard, mirroring the Activity tab.
WIP_PERIODS = [
    ("all", "All Dates"),
    ("today", "Today"),
    ("yesterday", "Yesterday"),
    ("this_week", "This Week"),
    ("last_week", "Last Week"),
    ("this_month", "This Month"),
]


def wip_period_range(label):
    """Map a quick-filter label to (date_min, date_max); (None, None) for all."""
    today = timezone.localdate()
    if label == "today":
        return today, today
    if label == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if label == "this_week":
        return today - timedelta(days=today.weekday()), today
    if label == "last_week":
        monday = today - timedelta(days=today.weekday())
        return monday - timedelta(days=7), monday - timedelta(days=1)
    if label == "this_month":
        return today.replace(day=1), today
    return None, None


def _totals(rows):
    return {
        key: sum((r[key] for r in rows), Decimal(0))
        for key in ("hours", "gross", "comp", "net")
    }


def wip_user_breakdown(user=None, date_min=None, date_max=None):
    """The unbilled WIP by-user view: (user_rows, user_donut, totals). When
    `user` is given, the breakdown is scoped to just that user (for the
    non-admin dashboard); otherwise it spans every user."""
    base = _wip_base(date_min, date_max)
    if user is not None:
        base = base.filter(user=user)

    by_user = base.values(
        "user_id", "user__first_name", "user__last_name", "user__username"
    ).annotate(hours_sum=Sum("hours"), gross=Sum(_FEE), comp=Sum(_COMP_FEE))

    user_rows = []
    for g in by_user:
        name = f"{g['user__first_name']} {g['user__last_name']}".strip()
        label = name or g["user__username"] or "Unassigned"
        user_rows.append(_row(label, g))
    user_rows.sort(key=lambda r: r["net"], reverse=True)

    totals = _totals(user_rows)
    total_net = totals["net"]
    for r in user_rows:
        r["pct"] = (r["net"] / total_net * 100) if total_net else Decimal(0)

    return user_rows, _donut(user_rows), totals


def build_wip_context(request):
    """Full template context for the WIP report, including donut payloads."""
    user_rows, user_donut, totals = wip_user_breakdown()
    total_net = totals["net"]

    by_matter = (
        _wip_base()
        .values("matter_id", "matter__name", "matter__client__name")
        .annotate(hours_sum=Sum("hours"), gross=Sum(_FEE), comp=Sum(_COMP_FEE))
    )
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
    for r in matter_rows:
        r["pct"] = (r["net"] / total_net * 100) if total_net else Decimal(0)

    if settings.DEBUG:
        matter_net = sum((r["net"] for r in matter_rows), Decimal(0))
        assert matter_net == total_net, f"WIP net mismatch: {matter_net} != {total_net}"

    return {
        "app": "reports",
        "subapp": "wip",
        "user_rows": user_rows,
        "matter_rows": matter_rows,
        "totals": totals,
        "user_donut": user_donut,
        "matter_donut": _donut(matter_rows, top_n=TOP_MATTERS),
    }


def _donut(rows, top_n=None):
    """Build a donut payload from rows. When `top_n` is set, keep the top N by
    gross and fold the rest into a trailing neutral "Other" slice."""
    ranked = sorted(rows, key=lambda r: r["gross"], reverse=True)
    has_other = top_n is not None and len(ranked) > top_n
    head = ranked[:top_n] if top_n is not None else ranked

    labels = [r["label"] for r in head]
    gross = [_money(r["gross"]) for r in head]
    net = [_money(r["net"]) for r in head]
    comp = [_money(r["comp"]) for r in head]

    if has_other:
        rest = ranked[top_n:]
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


def _cap_rows(rows, top_n):
    """Top `top_n` rows by gross (sorted by net for display) + an aggregated
    "Other" row, so the table shows the same buckets as the donut."""
    ranked = sorted(rows, key=lambda r: r["gross"], reverse=True)
    head = sorted(ranked[:top_n], key=lambda r: r["net"], reverse=True)
    rest = ranked[top_n:]
    if rest:
        head.append(
            {
                "label": "Other",
                "matter_id": None,
                "hours": sum((r["hours"] for r in rest), Decimal(0)),
                "gross": sum((r["gross"] for r in rest), Decimal(0)),
                "comp": sum((r["comp"] for r in rest), Decimal(0)),
                "net": sum((r["net"] for r in rest), Decimal(0)),
            }
        )
    return head


def _matter_rows(entries):
    """Per-matter rows (label + matter_id + hours/gross/comp/net) for `entries`."""
    rows = []
    for g in entries.values("matter_id", "matter__name").annotate(
        hours_sum=Sum("hours"), gross=Sum(_FEE), comp=Sum(_COMP_FEE)
    ):
        rows.append(
            {**_row(g["matter__name"] or "Unknown", g), "matter_id": g["matter_id"]}
        )
    return rows


def _matter_breakdown(entries, top_n):
    """(table_rows, donut, totals) for a by-matter breakdown: the table and donut
    share the top_n-by-gross + "Other" buckets; totals reflect every matter."""
    rows = _matter_rows(entries)
    return _cap_rows(rows, top_n), _donut(rows, top_n=top_n), _totals(rows)


def wip_user_matters(user, top_n=5, date_min=None, date_max=None):
    """A user's own unbilled WIP grouped by matter: (rows, donut, totals)."""
    return _matter_breakdown(_wip_base(date_min, date_max).filter(user=user), top_n)


def wip_matter_breakdown(top_n=5, date_min=None, date_max=None):
    """Firm-wide unbilled WIP grouped by matter: (rows, donut, totals)."""
    return _matter_breakdown(_wip_base(date_min, date_max), top_n)
