from tempfile import NamedTemporaryFile

from django.core.handlers.wsgi import WSGIRequest
from django.template.loader import render_to_string
from django.utils import timezone
from weasyprint import HTML

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.flat_fees.models import FlatFeeEntry
from apps.activity.time.models import TimeEntry
from apps.matters.models import Matter
from apps.matters.timekeepers import build_timekeepers
from apps.settings.models import Firm


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

    # Get all flat-fee entries for this matter
    flat_fee_entries = FlatFeeEntry.objects.filter(matter=matter).order_by("date", "id")

    # Calculate gross / comp / net totals for each category (mirrors the
    # invoice template's gross-minus-comp structure so the matter total
    # reflects what's actually billable).
    gross_time_fees = sum(entry.fee for entry in time_entries)
    comp_time_fees = sum(entry.fee for entry in time_entries if entry.comp)
    net_time_fees = gross_time_fees - comp_time_fees

    gross_time_hours = sum(entry.hours for entry in time_entries)
    comp_time_hours = sum(entry.hours for entry in time_entries if entry.comp)
    net_time_hours = gross_time_hours - comp_time_hours

    gross_expenses = sum(expense.amount for expense in expenses)
    comp_expenses = sum(expense.amount for expense in expenses if expense.comp)
    net_expenses = gross_expenses - comp_expenses

    gross_flat_fees = sum(entry.amount for entry in flat_fee_entries)
    comp_flat_fees = sum(entry.amount for entry in flat_fee_entries if entry.comp)
    net_flat_fees = gross_flat_fees - comp_flat_fees

    matter_total = net_time_fees + net_expenses + net_flat_fees

    context = {
        "matter": matter,
        "timekeepers": build_timekeepers(matter, time_entries),
        "time_entries": time_entries,
        "expenses": expenses,
        "flat_fee_entries": flat_fee_entries,
        "gross_time_fees": gross_time_fees,
        "gross_time_hours": gross_time_hours,
        "comp_time_hours": comp_time_hours,
        "net_time_hours": net_time_hours,
        "comp_time_fees": comp_time_fees,
        "net_time_fees": net_time_fees,
        "gross_expenses": gross_expenses,
        "comp_expenses": comp_expenses,
        "net_expenses": net_expenses,
        "gross_flat_fees": gross_flat_fees,
        "comp_flat_fees": comp_flat_fees,
        "net_flat_fees": net_flat_fees,
        "matter_total": matter_total,
        "current_date": timezone.localdate(),
        "company": Firm.objects.first(),
    }

    html_string = render_to_string("matters/activity-report.html", context)
    base_url = request.build_absolute_uri("/").rstrip("/")
    html = HTML(string=html_string, base_url=base_url)

    with NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        html.write_pdf(target=pdf_file.name)
        pdf_file.seek(0)

    return pdf_file
