from collections import defaultdict
from datetime import datetime
from tempfile import NamedTemporaryFile

from django.db.models.functions import TruncMonth
from django.template.loader import render_to_string
from weasyprint import HTML

from apps.intakes.models import Intake

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


def generate_intakes_pdf(date_from_obj, date_to_obj, request):
    """
    Generate a PDF of the intakes report with practice area breakdown
    """
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

    # Format dates for display
    date_from_str = date_from_obj.strftime("%B %d, %Y") if date_from_obj else None
    date_to_str = date_to_obj.strftime("%B %d, %Y") if date_to_obj else None

    context = {
        "intake_data": intake_data,
        "status_data": status_data,
        "total_intakes": total_intakes,
        "totals_by_practice_area": dict(totals_by_practice_area),
        "totals_by_status": dict(totals_by_status),
        "percentages_by_practice_area": percentages_by_practice_area,
        "percentages_by_status": percentages_by_status,
        "practice_areas": PRACTICE_AREAS,
        "intake_statuses": INTAKE_STATUSES,
        "date_from": date_from_str,
        "date_to": date_to_str,
        "generated_date": datetime.now().strftime("%B %d, %Y"),
    }

    html_string = render_to_string("reports/intakes/intakes_pdf.html", context)
    html = HTML(string=html_string, base_url=request.build_absolute_uri())

    with NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        html.write_pdf(target=pdf_file.name)
        pdf_file.seek(0)

    return pdf_file
