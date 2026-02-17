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

        # Calculate fee totals
        gross_fees = sum(entry.fee for entry in matter_time_entries)
        comp_fees = sum(entry.fee for entry in matter_time_entries if entry.comp)
        net_fees = gross_fees - comp_fees

        # Calculate expense totals
        gross_expenses = sum(entry.amount for entry in matter_expense_entries)
        comp_expenses = sum(
            entry.amount for entry in matter_expense_entries if entry.comp
        )
        net_expenses = gross_expenses - comp_expenses

        # Calculate total activity (entire matter, all-time)
        total_activity = data["matter"].value["total"]["net_fees_and_expenses"]

        # Calculate current month activity
        current_month = datetime.now().month
        current_year = datetime.now().year

        current_month_time = [
            entry
            for entry in matter_time_entries
            if entry.date.month == current_month and entry.date.year == current_year
        ]
        current_month_expenses = [
            entry
            for entry in matter_expense_entries
            if entry.date.month == current_month and entry.date.year == current_year
        ]

        current_month_fees = sum(
            entry.fee for entry in current_month_time if not entry.comp
        )
        current_month_expense_total = sum(
            entry.amount for entry in current_month_expenses if not entry.comp
        )
        current_month_activity = current_month_fees + current_month_expense_total

        matters_data.append(
            {
                "matter": data["matter"],
                "time_entries": matter_time_entries,
                "expense_entries": matter_expense_entries,
                "total_hours": sum(entry.hours for entry in matter_time_entries),
                "gross_fees": gross_fees,
                "comp_fees": comp_fees,
                "net_fees": net_fees,
                "gross_expenses": gross_expenses,
                "comp_expenses": comp_expenses,
                "net_expenses": net_expenses,
                "total_activity": total_activity,
                "current_month_activity": current_month_activity,
                # For backwards compatibility
                "total_fees": net_fees,
                "total_expenses": net_expenses,
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

    # Calculate Interpleader total (deferred)
    interpleader_total = sum(
        matter["total_fees"] + matter["total_expenses"]
        for matter in matters_data
        if matter["matter"].practice_area == "Interpleader"
    )

    context = {
        "client": client,
        "matters_data": matters_data,
        "time_entries_count": time_entries_count,
        "expense_entries_count": expense_entries_count,
        "total_hours": total_hours,
        "total_fees": total_fees,
        "total_expenses": total_expenses,
        "interpleader_total": interpleader_total,
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
