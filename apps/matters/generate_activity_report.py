from datetime import date
from tempfile import NamedTemporaryFile

from django.core.handlers.wsgi import WSGIRequest
from django.template.loader import render_to_string
from weasyprint import HTML

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.matters.models import Matter


def generate_activity_report(
    matter: Matter, request: WSGIRequest
) -> NamedTemporaryFile:
    """
    Generate a PDF activity report for the given matter showing all time entries and expenses
    """

    # Get all time entries for this matter
    time_entries = TimeEntry.objects.filter(matter=matter).order_by("date", "id")

    # Get all expenses for this matter
    expenses = ExpenseEntry.objects.filter(matter=matter).order_by("date", "id")

    # Calculate totals
    total_time_fees = sum(entry.fee for entry in time_entries)
    total_expenses = sum(expense.amount for expense in expenses)
    matter_total = total_time_fees + total_expenses

    context = {
        "matter": matter,
        "time_entries": time_entries,
        "expenses": expenses,
        "total_time_fees": total_time_fees,
        "total_expenses": total_expenses,
        "matter_total": matter_total,
        "current_date": date.today(),
    }

    html_string = render_to_string("matters/activity-report.html", context)
    base_url = request.build_absolute_uri("/").rstrip("/")
    html = HTML(string=html_string, base_url=base_url)

    with NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        html.write_pdf(target=pdf_file.name)
        pdf_file.seek(0)

    return pdf_file
