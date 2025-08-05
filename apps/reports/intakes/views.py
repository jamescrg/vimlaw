import os
from collections import defaultdict
from datetime import datetime

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models.functions import TruncMonth
from django.http import HttpResponse
from django.shortcuts import render

from apps.intakes.models import Intake
from apps.management.filter_manager import FilterManager

from .filters import IntakeReportFilter
from .functions import generate_intakes_pdf

# Define practice areas to match the choices in forms
PRACTICE_AREAS = [
    "General",
    "Boundary",
    "Title",
    "LLT - LL",
    "LLT - T",
    "QT",
    "HOA",
    "Fraud",
    "Construction",
]

# Define intake statuses to match the choices in forms
INTAKE_STATUSES = [
    "Open",
    "Pending",
    "Accepted",
    "Referred Out",
    "Client Declined",
    "Unresponsive",
]


@login_required
@staff_member_required
def intakes_index(request):
    # Get filter data from session
    filter_data = request.session.get("intakes_filter", {})

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

    # Get intakes
    intakes = Intake.objects.all()

    # Apply date filters
    if date_from_obj:
        intakes = intakes.filter(date__gte=date_from_obj)
    if date_to_obj:
        intakes = intakes.filter(date__lte=date_to_obj)

    # Get all months with intakes
    months_with_intakes = (
        intakes.annotate(month=TruncMonth("date"))
        .values("month")
        .distinct()
        .order_by("month")
    )

    # Build data structure with counts by practice area
    intake_data = []
    totals_by_practice_area = defaultdict(int)

    for month_data in months_with_intakes:
        if month_data["month"]:
            month_str = month_data["month"].strftime("%B %Y")
            row = {
                "month": month_str,
                "month_sort": month_data["month"],
                "practice_areas": {},
                "total": 0,
            }

            # Get counts for each practice area for this month
            for practice_area in PRACTICE_AREAS:
                count = intakes.filter(
                    date__year=month_data["month"].year,
                    date__month=month_data["month"].month,
                    practice_area=practice_area,
                ).count()
                row["practice_areas"][practice_area] = count
                row["total"] += count
                totals_by_practice_area[practice_area] += count

            # Calculate percentages for this month
            row["percentages"] = {}
            if row["total"] > 0:
                for practice_area in PRACTICE_AREAS:
                    percentage = (
                        row["practice_areas"][practice_area] / row["total"]
                    ) * 100
                    row["percentages"][practice_area] = round(percentage, 1)

            intake_data.append(row)

    # Calculate total intakes
    total_intakes = sum(row["total"] for row in intake_data)

    # Calculate overall percentages for each practice area
    percentages_by_practice_area = {}
    if total_intakes > 0:
        for practice_area in PRACTICE_AREAS:
            percentage = (totals_by_practice_area[practice_area] / total_intakes) * 100
            percentages_by_practice_area[practice_area] = round(percentage, 1)

    # Build data structure with counts by status (for conversion table)
    status_data = []
    totals_by_status = defaultdict(int)

    for month_data in months_with_intakes:
        if month_data["month"]:
            month_str = month_data["month"].strftime("%B %Y")
            row = {
                "month": month_str,
                "month_sort": month_data["month"],
                "statuses": {},
                "total": 0,
            }

            # Get counts for each status for this month
            for status in INTAKE_STATUSES:
                count = intakes.filter(
                    date__year=month_data["month"].year,
                    date__month=month_data["month"].month,
                    status=status,
                ).count()
                row["statuses"][status] = count
                row["total"] += count
                totals_by_status[status] += count

            # Calculate percentages for this month
            row["percentages"] = {}
            if row["total"] > 0:
                for status in INTAKE_STATUSES:
                    percentage = (row["statuses"][status] / row["total"]) * 100
                    row["percentages"][status] = round(percentage, 1)

            status_data.append(row)

    # Calculate overall percentages for each status
    percentages_by_status = {}
    if total_intakes > 0:
        for status in INTAKE_STATUSES:
            percentage = (totals_by_status[status] / total_intakes) * 100
            percentages_by_status[status] = round(percentage, 1)

    context = {
        "app": "reports",
        "subapp": "intakes",
        "intake_data": intake_data,
        "status_data": status_data,
        "total_intakes": total_intakes,
        "totals_by_practice_area": dict(totals_by_practice_area),
        "totals_by_status": dict(totals_by_status),
        "percentages_by_practice_area": percentages_by_practice_area,
        "percentages_by_status": percentages_by_status,
        "practice_areas": PRACTICE_AREAS,
        "intake_statuses": INTAKE_STATUSES,
        "date_from": date_from,
        "date_to": date_to,
    }

    return render(request, "reports/intakes/main.html", context)


@login_required
@staff_member_required
def intakes_list(request):
    # Get filter data from session
    filter_data = request.session.get("intakes_filter", {})

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

    # Get intakes
    intakes = Intake.objects.all()

    # Apply date filters
    if date_from_obj:
        intakes = intakes.filter(date__gte=date_from_obj)
    if date_to_obj:
        intakes = intakes.filter(date__lte=date_to_obj)

    # Get all months with intakes
    months_with_intakes = (
        intakes.annotate(month=TruncMonth("date"))
        .values("month")
        .distinct()
        .order_by("month")
    )

    # Build data structure with counts by practice area
    intake_data = []
    totals_by_practice_area = defaultdict(int)

    for month_data in months_with_intakes:
        if month_data["month"]:
            month_str = month_data["month"].strftime("%B %Y")
            row = {
                "month": month_str,
                "month_sort": month_data["month"],
                "practice_areas": {},
                "total": 0,
            }

            # Get counts for each practice area for this month
            for practice_area in PRACTICE_AREAS:
                count = intakes.filter(
                    date__year=month_data["month"].year,
                    date__month=month_data["month"].month,
                    practice_area=practice_area,
                ).count()
                row["practice_areas"][practice_area] = count
                row["total"] += count
                totals_by_practice_area[practice_area] += count

            # Calculate percentages for this month
            row["percentages"] = {}
            if row["total"] > 0:
                for practice_area in PRACTICE_AREAS:
                    percentage = (
                        row["practice_areas"][practice_area] / row["total"]
                    ) * 100
                    row["percentages"][practice_area] = round(percentage, 1)

            intake_data.append(row)

    # Calculate total intakes
    total_intakes = sum(row["total"] for row in intake_data)

    # Calculate overall percentages for each practice area
    percentages_by_practice_area = {}
    if total_intakes > 0:
        for practice_area in PRACTICE_AREAS:
            percentage = (totals_by_practice_area[practice_area] / total_intakes) * 100
            percentages_by_practice_area[practice_area] = round(percentage, 1)

    # Build data structure with counts by status (for conversion table)
    status_data = []
    totals_by_status = defaultdict(int)

    for month_data in months_with_intakes:
        if month_data["month"]:
            month_str = month_data["month"].strftime("%B %Y")
            row = {
                "month": month_str,
                "month_sort": month_data["month"],
                "statuses": {},
                "total": 0,
            }

            # Get counts for each status for this month
            for status in INTAKE_STATUSES:
                count = intakes.filter(
                    date__year=month_data["month"].year,
                    date__month=month_data["month"].month,
                    status=status,
                ).count()
                row["statuses"][status] = count
                row["total"] += count
                totals_by_status[status] += count

            # Calculate percentages for this month
            row["percentages"] = {}
            if row["total"] > 0:
                for status in INTAKE_STATUSES:
                    percentage = (row["statuses"][status] / row["total"]) * 100
                    row["percentages"][status] = round(percentage, 1)

            status_data.append(row)

    # Calculate overall percentages for each status
    percentages_by_status = {}
    if total_intakes > 0:
        for status in INTAKE_STATUSES:
            percentage = (totals_by_status[status] / total_intakes) * 100
            percentages_by_status[status] = round(percentage, 1)

    context = {
        "app": "reports",
        "subapp": "intakes",
        "intake_data": intake_data,
        "status_data": status_data,
        "total_intakes": total_intakes,
        "totals_by_practice_area": dict(totals_by_practice_area),
        "totals_by_status": dict(totals_by_status),
        "percentages_by_practice_area": percentages_by_practice_area,
        "percentages_by_status": percentages_by_status,
        "practice_areas": PRACTICE_AREAS,
        "intake_statuses": INTAKE_STATUSES,
        "date_from": date_from,
        "date_to": date_to,
    }

    return render(request, "reports/intakes/list.html", context)


@login_required
@staff_member_required
def intakes_filter(request):
    filter_manager = FilterManager(request, IntakeReportFilter, "intakes_filter")

    if filter_manager.process_filter():
        return HttpResponse(status=204, headers={"HX-Trigger": "intakesChanged"})

    # Get current filter data from session for display
    filter_data = request.session.get("intakes_filter", {})

    return render(request, "reports/intakes/filter.html", {"filter_data": filter_data})


@login_required
@staff_member_required
def intakes_pdf(request):
    """Export intakes report as PDF"""

    # Get filter data from session
    filter_data = request.session.get("intakes_filter", {})

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

    # Generate PDF
    pdf_file = generate_intakes_pdf(date_from_obj, date_to_obj, request)

    # Create response
    with open(pdf_file.name, "rb") as f:
        response = HttpResponse(f.read(), content_type="application/pdf")

    # Set filename for download
    current_date = datetime.now().strftime("%Y-%m-%d")
    filename = f"Intakes_Report_{current_date}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    # Clean up temporary file
    os.unlink(pdf_file.name)

    return response
