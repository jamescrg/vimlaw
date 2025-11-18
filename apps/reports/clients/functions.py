from datetime import datetime
from tempfile import NamedTemporaryFile

from django.core.handlers.wsgi import WSGIRequest
from django.template.loader import render_to_string
from weasyprint import HTML

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.contacts.models import Contact


def generate_client_statement_pdf(
    client: Contact, date_from=None, date_to=None, request: WSGIRequest = None
) -> NamedTemporaryFile:
    """
    Generate a PDF activity report for the given client
    """

    # Get time entries
    time_entries = TimeEntry.objects.filter(matter__client=client).order_by(
        "matter__name", "-date", "-id"
    )
    if date_from:
        time_entries = time_entries.filter(date__gte=date_from)
    if date_to:
        time_entries = time_entries.filter(date__lte=date_to)

    # Get expense entries
    expense_entries = ExpenseEntry.objects.filter(matter__client=client).order_by(
        "matter__name", "-date", "-id"
    )
    if date_from:
        expense_entries = expense_entries.filter(date__gte=date_from)
    if date_to:
        expense_entries = expense_entries.filter(date__lte=date_to)

    # Group entries by matter
    from collections import defaultdict

    matters_dict = defaultdict(lambda: {"time_entries": [], "expense_entries": []})

    for entry in time_entries:
        matter_key = entry.matter.id if entry.matter else None
        if matter_key:
            matters_dict[matter_key]["matter"] = entry.matter
            matters_dict[matter_key]["time_entries"].append(entry)

    for entry in expense_entries:
        matter_key = entry.matter.id if entry.matter else None
        if matter_key:
            if "matter" not in matters_dict[matter_key]:
                matters_dict[matter_key]["matter"] = entry.matter
            matters_dict[matter_key]["expense_entries"].append(entry)

    # Convert to list and calculate totals per matter
    matters_data = []
    for matter_id, data in matters_dict.items():
        matter_time_entries = data["time_entries"]
        matter_expense_entries = data["expense_entries"]

        matters_data.append(
            {
                "matter": data["matter"],
                "time_entries": matter_time_entries,
                "expense_entries": matter_expense_entries,
                "total_hours": sum(entry.hours for entry in matter_time_entries),
                "total_fees": sum(entry.fee for entry in matter_time_entries),
                "total_expenses": sum(entry.amount for entry in matter_expense_entries),
            }
        )

    # Sort matters by name
    matters_data.sort(key=lambda x: x["matter"].name)

    # Calculate overall totals
    total_hours = sum(matter["total_hours"] for matter in matters_data)
    total_fees = sum(matter["total_fees"] for matter in matters_data)
    total_expenses = sum(matter["total_expenses"] for matter in matters_data)
    time_entries_count = sum(len(matter["time_entries"]) for matter in matters_data)
    expense_entries_count = sum(
        len(matter["expense_entries"]) for matter in matters_data
    )

    # Campbell & Brannon prepayment logic
    is_cb_client = client and client.name == "Campbell & Brannon"
    prepayment = 3500 if is_cb_client else 0
    total_activity = total_fees + total_expenses
    amount_due = max(0, total_activity - prepayment) if is_cb_client else 0

    context = {
        "client": client,
        "matters_data": matters_data,
        "time_entries_count": time_entries_count,
        "expense_entries_count": expense_entries_count,
        "total_hours": total_hours,
        "total_fees": total_fees,
        "total_expenses": total_expenses,
        "is_cb_client": is_cb_client,
        "prepayment": prepayment,
        "amount_due": amount_due,
        "date_from": date_from,
        "date_to": date_to,
        "current_date": datetime.now().date(),
    }

    html_string = render_to_string("reports/clients/statement_pdf.html", context)

    if request:
        base_url = request.build_absolute_uri("/").rstrip("/")
    else:
        base_url = "file://"

    html = HTML(string=html_string, base_url=base_url)

    with NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        html.write_pdf(target=pdf_file.name)
        pdf_file.seek(0)

    return pdf_file
