from datetime import date

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
            # Get time entries for this user and month
            entries = TimeEntry.objects.filter(
                user=user,
                date__year=month_info["year"],
                date__month=month_info["month"],
            )

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
    }

    return render(request, "reports/activity/main.html", context)


@login_required
@staff_member_required
def activity_list(request):
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
            # Get time entries for this user and month
            entries = TimeEntry.objects.filter(
                user=user,
                date__year=month_info["year"],
                date__month=month_info["month"],
            )

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
    }

    return render(request, "reports/activity/list.html", context)
