from datetime import datetime
from tempfile import NamedTemporaryFile

from django.core.handlers.wsgi import WSGIRequest
from django.template.loader import render_to_string
from weasyprint import HTML

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.contacts.models import Contact


def generate_client_detail_pdf(
    client: Contact, date_from=None, date_to=None, request: WSGIRequest = None
) -> NamedTemporaryFile:
    """
    Generate a PDF activity report for the given client
    """

    # Get time entries
    time_entries = TimeEntry.objects.filter(matter__client=client).order_by(
        "date", "id"
    )
    if date_from:
        time_entries = time_entries.filter(date__gte=date_from)
    if date_to:
        time_entries = time_entries.filter(date__lte=date_to)

    # Get expense entries
    expense_entries = ExpenseEntry.objects.filter(matter__client=client).order_by(
        "date", "id"
    )
    if date_from:
        expense_entries = expense_entries.filter(date__gte=date_from)
    if date_to:
        expense_entries = expense_entries.filter(date__lte=date_to)

    # Calculate totals
    total_hours = sum(entry.hours for entry in time_entries)
    total_fees = sum(entry.fee for entry in time_entries)
    total_expenses = sum(entry.amount for entry in expense_entries)

    context = {
        "client": client,
        "time_entries": time_entries,
        "expense_entries": expense_entries,
        "time_entries_count": len(time_entries),
        "expense_entries_count": len(expense_entries),
        "total_hours": total_hours,
        "total_fees": total_fees,
        "total_expenses": total_expenses,
        "date_from": date_from,
        "date_to": date_to,
        "current_date": datetime.now().date(),
    }

    html_string = render_to_string("reports/clients/client_detail_pdf.html", context)

    if request:
        base_url = request.build_absolute_uri("/").rstrip("/")
    else:
        base_url = "file://"

    html = HTML(string=html_string, base_url=base_url)

    with NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        html.write_pdf(target=pdf_file.name)
        pdf_file.seek(0)

    return pdf_file
