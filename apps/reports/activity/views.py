from datetime import date, datetime

from dateutil.relativedelta import relativedelta
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render

from apps.accounts.models import CustomUser
from apps.activity.time.models import TimeEntry


@login_required
@staff_member_required
def activity_index(request):
    # Get filter data from session
    filter_data = request.session.get("reports_filter", {})

    # Set date filter objects (None means no date filtering)
    date_from_obj = None
    date_to_obj = None
    date_from = filter_data.get("date_from")
    date_to = filter_data.get("date_to")

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

    # Calculate the last 6 months (oldest to newest)
    today = date.today()
    months = []
    for i in range(5, -1, -1):  # Reverse order: 5, 4, 3, 2, 1, 0
        month_date = today - relativedelta(months=i)
        months.append(
            {
                "date": month_date,
                "name": month_date.strftime("%B %Y"),
                "year": month_date.year,
                "month": month_date.month,
            }
        )

    # Get all users who have time entries
    users = (
        CustomUser.objects.filter(timeentry__date__gte=today - relativedelta(months=6))
        .distinct()
        .order_by("first_name", "last_name")
    )

    # Build data structure for each user and month
    activity_data = []
    for user in users:
        user_data = {"user": user, "months": []}

        total_hours = 0
        for month_info in months:
            # Get time entries for this user and month with optional filtering
            entries = TimeEntry.objects.filter(
                user=user,
                date__year=month_info["year"],
                date__month=month_info["month"],
            )

            # Apply additional date filtering if specified
            if date_from_obj:
                entries = entries.filter(date__gte=date_from_obj)
            if date_to_obj:
                entries = entries.filter(date__lte=date_to_obj)

            month_hours = entries.aggregate(Sum("hours"))["hours__sum"] or 0
            total_hours += month_hours

            user_data["months"].append(
                {
                    "name": month_info["name"],
                    "hours": month_hours,
                    "entries_count": entries.count(),
                }
            )

        user_data["total_hours"] = total_hours
        activity_data.append(user_data)

    context = {
        "app": "reports",
        "subapp": "activity",
        "activity_data": activity_data,
        "months": [m["name"] for m in months],
        "date_from": date_from,
        "date_to": date_to,
    }

    return render(request, "reports/activity/main.html", context)


@login_required
@staff_member_required
def activity_list(request):
    # Get filter data from session
    filter_data = request.session.get("reports_filter", {})

    # Set date filter objects (None means no date filtering)
    date_from_obj = None
    date_to_obj = None
    date_from = filter_data.get("date_from")
    date_to = filter_data.get("date_to")

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

    # Calculate the last 6 months (oldest to newest)
    today = date.today()
    months = []
    for i in range(5, -1, -1):  # Reverse order: 5, 4, 3, 2, 1, 0
        month_date = today - relativedelta(months=i)
        months.append(
            {
                "date": month_date,
                "name": month_date.strftime("%B %Y"),
                "year": month_date.year,
                "month": month_date.month,
            }
        )

    # Get all users who have time entries
    users = (
        CustomUser.objects.filter(timeentry__date__gte=today - relativedelta(months=6))
        .distinct()
        .order_by("first_name", "last_name")
    )

    # Build data structure for each user and month
    activity_data = []
    for user in users:
        user_data = {"user": user, "months": []}

        total_hours = 0
        for month_info in months:
            # Get time entries for this user and month with optional filtering
            entries = TimeEntry.objects.filter(
                user=user,
                date__year=month_info["year"],
                date__month=month_info["month"],
            )

            # Apply additional date filtering if specified
            if date_from_obj:
                entries = entries.filter(date__gte=date_from_obj)
            if date_to_obj:
                entries = entries.filter(date__lte=date_to_obj)

            month_hours = entries.aggregate(Sum("hours"))["hours__sum"] or 0
            total_hours += month_hours

            user_data["months"].append(
                {
                    "name": month_info["name"],
                    "hours": month_hours,
                    "entries_count": entries.count(),
                }
            )

        user_data["total_hours"] = total_hours
        activity_data.append(user_data)

    context = {
        "app": "reports",
        "subapp": "activity",
        "activity_data": activity_data,
        "months": [m["name"] for m in months],
        "date_from": date_from,
        "date_to": date_to,
    }

    return render(request, "reports/activity/list.html", context)
