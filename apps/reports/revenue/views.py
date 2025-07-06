from datetime import date

from dateutil.relativedelta import relativedelta
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render

from apps.invoicing.payments.models import Payment


@login_required
@staff_member_required
def revenue_index(request):
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

    # Build revenue data for each month
    revenue_data = []
    total_revenue = 0

    for month_info in months:
        # Get payments for this month
        payments = Payment.objects.filter(
            date__year=month_info["year"], date__month=month_info["month"]
        )

        month_revenue = payments.aggregate(Sum("amount"))["amount__sum"] or 0
        total_revenue += month_revenue

        revenue_data.append(
            {
                "name": month_info["name"],
                "revenue": month_revenue,
                "payments_count": payments.count(),
            }
        )

    context = {
        "app": "reports",
        "subapp": "revenue",
        "revenue_data": revenue_data,
        "total_revenue": total_revenue,
        "months": [m["name"] for m in months],
    }

    return render(request, "reports/revenue/main.html", context)


@login_required
@staff_member_required
def revenue_list(request):
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

    # Build revenue data for each month
    revenue_data = []
    total_revenue = 0

    for month_info in months:
        # Get payments for this month
        payments = Payment.objects.filter(
            date__year=month_info["year"], date__month=month_info["month"]
        )

        month_revenue = payments.aggregate(Sum("amount"))["amount__sum"] or 0
        total_revenue += month_revenue

        revenue_data.append(
            {
                "name": month_info["name"],
                "revenue": month_revenue,
                "payments_count": payments.count(),
            }
        )

    context = {
        "app": "reports",
        "subapp": "revenue",
        "revenue_data": revenue_data,
        "total_revenue": total_revenue,
        "months": [m["name"] for m in months],
    }

    return render(request, "reports/revenue/list.html", context)
