from datetime import date, datetime
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import F, Sum
from django.http import HttpResponse
from django.shortcuts import render

from apps.accounts.models import CustomUser
from apps.activity.time.models import TimeEntry
from apps.management.filter_manager import FilterManager

from .filters import ActivityReportFilter


@login_required
@staff_member_required
def activity_index(request):
    # Get filter data from session
    filter_data = request.session.get("activity_filter", {})

    # Set date filter objects (None means no date filtering)
    date_from_obj = None
    date_to_obj = None
    date_from = filter_data.get("date_from")
    date_to = filter_data.get("date_to")

    # Default to excluding inactive users if not specified
    exclude_inactive_str = filter_data.get("exclude_inactive", "on")
    exclude_inactive = exclude_inactive_str in ["on", "true", "1"]

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

    # Calculate months based on filter or default to last 6 months
    today = date.today()
    months = []

    if date_from_obj and date_to_obj:
        # Use filtered date range
        current_date = date_from_obj.replace(day=1)  # Start at beginning of month
        end_date = date_to_obj

        while current_date <= end_date:
            months.append(
                {
                    "date": current_date,
                    "name": current_date.strftime("%B %Y"),
                    "year": current_date.year,
                    "month": current_date.month,
                }
            )
            current_date = current_date + relativedelta(months=1)
    elif date_from_obj:
        # From date_from to today
        current_date = date_from_obj.replace(day=1)

        while current_date <= today:
            months.append(
                {
                    "date": current_date,
                    "name": current_date.strftime("%B %Y"),
                    "year": current_date.year,
                    "month": current_date.month,
                }
            )
            current_date = current_date + relativedelta(months=1)
    elif date_to_obj:
        # Last 6 months up to date_to
        for i in range(5, -1, -1):
            month_date = date_to_obj - relativedelta(months=i)
            if month_date <= date_to_obj:
                months.append(
                    {
                        "date": month_date,
                        "name": month_date.strftime("%B %Y"),
                        "year": month_date.year,
                        "month": month_date.month,
                    }
                )
    else:
        # Default: current calendar month
        months.append(
            {
                "date": today,
                "name": today.strftime("%B %Y"),
                "year": today.year,
                "month": today.month,
            }
        )
        date_from = today.replace(day=1).strftime("%Y-%m-%d")
        date_from_obj = today.replace(day=1)

    # Get all users who have time entries
    # Determine the date range for user filtering
    if date_from_obj:
        filter_start = date_from_obj
    else:
        filter_start = today.replace(day=1)

    users_query = CustomUser.objects.filter(timeentry__date__gte=filter_start)

    # Exclude inactive users if requested
    if exclude_inactive:
        users_query = users_query.filter(is_active=True)

    users = users_query.distinct().order_by("first_name", "last_name")

    # Build data structure with months as rows and users as columns
    activity_data = []
    user_totals = {user.id: {"hours": 0, "fees": Decimal(0)} for user in users}

    for month_info in months:
        month_data = {
            "name": month_info["name"],
            "year": month_info["year"],
            "month": month_info["month"],
            "users": [],
        }

        month_total_hours = 0
        month_total_fees = Decimal(0)

        for user in users:
            # Get time entries for this user and month
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

            # Update totals
            user_totals[user.id]["hours"] += hours
            user_totals[user.id]["fees"] += fees
            month_total_hours += hours
            month_total_fees += fees

        month_data["total_hours"] = month_total_hours
        month_data["total_fees"] = month_total_fees
        activity_data.append(month_data)

    # Calculate grand totals
    grand_total_hours = sum(totals["hours"] for totals in user_totals.values())
    grand_total_fees = sum(totals["fees"] for totals in user_totals.values())

    # Calculate averages per month
    num_months = len(months) if months else 1  # Avoid division by zero
    user_averages = {}
    for user_id, totals in user_totals.items():
        user_averages[user_id] = {
            "hours": totals["hours"] / num_months,
            "fees": totals["fees"] / num_months,
        }

    grand_average_hours = grand_total_hours / num_months
    grand_average_fees = grand_total_fees / num_months

    context = {
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
    }

    return render(request, "reports/activity/main.html", context)


@login_required
@staff_member_required
def activity_list(request):
    # Get filter data from session
    filter_data = request.session.get("activity_filter", {})

    # Set date filter objects (None means no date filtering)
    date_from_obj = None
    date_to_obj = None
    date_from = filter_data.get("date_from")
    date_to = filter_data.get("date_to")

    # Default to excluding inactive users if not specified
    exclude_inactive_str = filter_data.get("exclude_inactive", "on")
    exclude_inactive = exclude_inactive_str in ["on", "true", "1"]

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

    # Calculate months based on filter or default to last 6 months
    today = date.today()
    months = []

    if date_from_obj and date_to_obj:
        # Use filtered date range
        current_date = date_from_obj.replace(day=1)  # Start at beginning of month
        end_date = date_to_obj

        while current_date <= end_date:
            months.append(
                {
                    "date": current_date,
                    "name": current_date.strftime("%B %Y"),
                    "year": current_date.year,
                    "month": current_date.month,
                }
            )
            current_date = current_date + relativedelta(months=1)
    elif date_from_obj:
        # From date_from to today
        current_date = date_from_obj.replace(day=1)

        while current_date <= today:
            months.append(
                {
                    "date": current_date,
                    "name": current_date.strftime("%B %Y"),
                    "year": current_date.year,
                    "month": current_date.month,
                }
            )
            current_date = current_date + relativedelta(months=1)
    elif date_to_obj:
        # Last 6 months up to date_to
        for i in range(5, -1, -1):
            month_date = date_to_obj - relativedelta(months=i)
            if month_date <= date_to_obj:
                months.append(
                    {
                        "date": month_date,
                        "name": month_date.strftime("%B %Y"),
                        "year": month_date.year,
                        "month": month_date.month,
                    }
                )
    else:
        # Default: current calendar month
        months.append(
            {
                "date": today,
                "name": today.strftime("%B %Y"),
                "year": today.year,
                "month": today.month,
            }
        )
        date_from = today.replace(day=1).strftime("%Y-%m-%d")
        date_from_obj = today.replace(day=1)

    # Get all users who have time entries
    # Determine the date range for user filtering
    if date_from_obj:
        filter_start = date_from_obj
    else:
        filter_start = today.replace(day=1)

    users_query = CustomUser.objects.filter(timeentry__date__gte=filter_start)

    # Exclude inactive users if requested
    if exclude_inactive:
        users_query = users_query.filter(is_active=True)

    users = users_query.distinct().order_by("first_name", "last_name")

    # Build data structure with months as rows and users as columns
    activity_data = []
    user_totals = {user.id: {"hours": 0, "fees": Decimal(0)} for user in users}

    for month_info in months:
        month_data = {
            "name": month_info["name"],
            "year": month_info["year"],
            "month": month_info["month"],
            "users": [],
        }

        month_total_hours = 0
        month_total_fees = Decimal(0)

        for user in users:
            # Get time entries for this user and month
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

            # Update totals
            user_totals[user.id]["hours"] += hours
            user_totals[user.id]["fees"] += fees
            month_total_hours += hours
            month_total_fees += fees

        month_data["total_hours"] = month_total_hours
        month_data["total_fees"] = month_total_fees
        activity_data.append(month_data)

    # Calculate grand totals
    grand_total_hours = sum(totals["hours"] for totals in user_totals.values())
    grand_total_fees = sum(totals["fees"] for totals in user_totals.values())

    # Calculate averages per month
    num_months = len(months) if months else 1  # Avoid division by zero
    user_averages = {}
    for user_id, totals in user_totals.items():
        user_averages[user_id] = {
            "hours": totals["hours"] / num_months,
            "fees": totals["fees"] / num_months,
        }

    grand_average_hours = grand_total_hours / num_months
    grand_average_fees = grand_total_fees / num_months

    context = {
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
    }

    return render(request, "reports/activity/list.html", context)


@login_required
@staff_member_required
def activity_filter(request):
    filter_manager = FilterManager(request, ActivityReportFilter, "activity_filter")

    if filter_manager.process_filter():
        return HttpResponse(status=204, headers={"HX-Trigger": "activityChanged"})

    # Get current filter data from session for display
    filter_data = request.session.get("activity_filter", {})

    return render(request, "reports/activity/filter.html", {"filter_data": filter_data})
