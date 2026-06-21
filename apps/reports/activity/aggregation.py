"""Shared data aggregation for the Activity report.

`build_activity_context` is the single source of truth for both `activity_index`
and `activity_list` (previously ~190 lines of duplicated logic). It resolves the
session date filter into a list of months, aggregates `TimeEntry` rows by user
(for the table) and by matter (top-N + "Other"), and assembles `chart_payload`
— a JSON-safe dict consumed by the stacked bar chart via `json_script`.
"""

from datetime import date, datetime
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.db.models import F, Sum

from apps.accounts.models import CustomUser
from apps.activity.time.models import TimeEntry

# Number of distinct matters charted before the rest roll up into "Other".
TOP_MATTERS = 8


def _resolve_months(filter_data):
    """Return (months, date_from, date_to, date_from_obj, exclude_inactive).

    Mirrors the original view logic: an explicit range drives the month list,
    a single bound extends to today / back six months, and the empty case
    defaults to the current calendar month.
    """
    date_from = filter_data.get("date_from")
    date_to = filter_data.get("date_to")

    exclude_inactive_str = filter_data.get("exclude_inactive", "on")
    exclude_inactive = exclude_inactive_str in ["on", "true", "1"]

    date_from_obj = None
    date_to_obj = None
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
        except ValueError:
            date_from = None
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").date()
        except ValueError:
            date_to = None

    today = date.today()
    months = []

    def add_month(month_date):
        months.append(
            {
                "date": month_date,
                "name": month_date.strftime("%B %Y"),
                "year": month_date.year,
                "month": month_date.month,
            }
        )

    if date_from_obj and date_to_obj:
        current_date = date_from_obj.replace(day=1)
        while current_date <= date_to_obj:
            add_month(current_date)
            current_date = current_date + relativedelta(months=1)
    elif date_from_obj:
        current_date = date_from_obj.replace(day=1)
        while current_date <= today:
            add_month(current_date)
            current_date = current_date + relativedelta(months=1)
    elif date_to_obj:
        for i in range(5, -1, -1):
            add_month(date_to_obj - relativedelta(months=i))
    else:
        add_month(today)
        date_from = today.replace(day=1).strftime("%Y-%m-%d")
        date_from_obj = today.replace(day=1)

    return months, date_from, date_to, date_from_obj, exclude_inactive


def _build_matter_series(months):
    """Per-month billable hours/fees grouped by matter, capped at TOP_MATTERS.

    Returns a list of series dicts aligned to `months`:
        [{"label": "Acme v. Roe", "hours": [...], "fees": [...]}, ..., {"label": "Other", ...}]
    Matters outside the top-N (ranked by total hours over the window) fold into
    a trailing "Other" bucket.
    """
    if not months:
        return []

    window_start = months[0]["date"].replace(day=1)
    window_end = months[-1]["date"].replace(day=1) + relativedelta(months=1)

    ranking = (
        TimeEntry.objects.filter(
            matter__billable=True,
            date__gte=window_start,
            date__lt=window_end,
        )
        .values("matter_id", "matter__name")
        .annotate(total=Sum("hours"))
        .order_by("-total")
    )

    top = list(ranking[:TOP_MATTERS])
    top_ids = [row["matter_id"] for row in top]
    has_other = ranking.count() > len(top)

    # Stable order: top matters first (by total hours), then Other.
    series = [
        {
            "matter_id": row["matter_id"],
            "label": row["matter__name"] or "(no name)",
            "hours": [],
            "fees": [],
        }
        for row in top
    ]
    other = {"hours": [], "fees": []} if has_other else None

    for month_info in months:
        grouped = (
            TimeEntry.objects.filter(
                matter__billable=True,
                date__year=month_info["year"],
                date__month=month_info["month"],
            )
            .values("matter_id")
            .annotate(
                hours_sum=Sum("hours"),
                fees_sum=Sum(F("hours") * F("rate")),
            )
        )
        by_matter = {row["matter_id"]: row for row in grouped}

        other_hours = Decimal(0)
        other_fees = Decimal(0)
        for row in grouped:
            if row["matter_id"] not in top_ids:
                other_hours += row["hours_sum"] or 0
                other_fees += row["fees_sum"] or Decimal(0)

        for s in series:
            row = by_matter.get(s["matter_id"])
            s["hours"].append(float(row["hours_sum"] or 0) if row else 0.0)
            s["fees"].append(round(float(row["fees_sum"] or 0), 2) if row else 0.0)

        if other is not None:
            other["hours"].append(float(other_hours))
            other["fees"].append(round(float(other_fees), 2))

    result = [
        {"label": s["label"], "hours": s["hours"], "fees": s["fees"]} for s in series
    ]
    if other is not None:
        result.append(
            {"label": "Other", "hours": other["hours"], "fees": other["fees"]}
        )
    return result


def build_activity_context(request):
    """Full template context for the activity report, including `chart_payload`."""
    filter_data = request.session.get("activity_filter", {})
    (
        months,
        date_from,
        date_to,
        date_from_obj,
        exclude_inactive,
    ) = _resolve_months(filter_data)

    today = date.today()
    filter_start = date_from_obj if date_from_obj else today.replace(day=1)

    users_query = CustomUser.objects.filter(timeentry__date__gte=filter_start)
    if exclude_inactive:
        users_query = users_query.filter(is_active=True)
    users = users_query.distinct().order_by("first_name", "last_name")

    # Month-by-user grid for the table, plus aligned per-user arrays for the chart.
    activity_data = []
    user_totals = {user.id: {"hours": 0, "fees": Decimal(0)} for user in users}
    user_series = [
        {
            "label": f"{u.first_name} {u.last_name}".strip() or u.get_username(),
            "hours": [],
            "fees": [],
        }
        for u in users
    ]

    for month_info in months:
        month_data = {
            "name": month_info["name"],
            "year": month_info["year"],
            "month": month_info["month"],
            "users": [],
        }
        month_total_hours = 0
        month_total_fees = Decimal(0)

        for idx, user in enumerate(users):
            entries = TimeEntry.objects.filter(
                user=user,
                date__year=month_info["year"],
                date__month=month_info["month"],
            )
            billable_entries = entries.filter(matter__billable=True)
            admin_entries = entries.filter(matter__billable=False)

            hours = billable_entries.aggregate(Sum("hours"))["hours__sum"] or 0
            fees = billable_entries.aggregate(total_fees=Sum(F("hours") * F("rate")))[
                "total_fees"
            ] or Decimal(0)
            admin_hours = admin_entries.aggregate(Sum("hours"))["hours__sum"] or 0

            month_data["users"].append(
                {
                    "user": user,
                    "hours": hours,
                    "fees": fees,
                    "admin_hours": admin_hours,
                    "entries_count": billable_entries.count(),
                }
            )

            user_totals[user.id]["hours"] += hours
            user_totals[user.id]["fees"] += fees
            month_total_hours += hours
            month_total_fees += fees

            user_series[idx]["hours"].append(float(hours))
            user_series[idx]["fees"].append(round(float(fees), 2))

        month_data["total_hours"] = month_total_hours
        month_data["total_fees"] = month_total_fees
        activity_data.append(month_data)

    grand_total_hours = sum(totals["hours"] for totals in user_totals.values())
    grand_total_fees = sum(totals["fees"] for totals in user_totals.values())

    num_months = len(months) if months else 1
    user_averages = {
        user_id: {
            "hours": totals["hours"] / num_months,
            "fees": totals["fees"] / num_months,
        }
        for user_id, totals in user_totals.items()
    }
    grand_average_hours = grand_total_hours / num_months
    grand_average_fees = grand_total_fees / num_months

    chart_payload = {
        "months": [m["name"] for m in months],
        "series": {
            "user": user_series,
            "matter": _build_matter_series(months),
        },
    }

    return {
        "app": "reports",
        "subapp": "activity",
        "activity_data": activity_data,
        "users": users,
        "user_totals": user_totals,
        "user_averages": user_averages,
        "grand_total_hours": grand_total_hours,
        "grand_total_fees": grand_total_fees,
        "grand_average_hours": grand_average_hours,
        "grand_average_fees": grand_average_fees,
        "months": [m["name"] for m in months],
        "date_from": date_from,
        "date_to": date_to,
        "exclude_inactive": exclude_inactive,
        "chart_payload": chart_payload,
    }
