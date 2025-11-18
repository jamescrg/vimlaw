from datetime import datetime

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import render

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.contacts.models import Contact
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment
from apps.management.filter_manager import FilterManager

from .filters import ClientReportFilter
from .functions import generate_client_statement_pdf


@login_required
@staff_member_required
def clients_index(request):
    # Get sorting parameters
    sort_by = request.GET.get("sort", "client_name")
    sort_direction = request.GET.get("direction", "asc")

    # Get filter data from session
    filter_data = request.session.get("clients_filter", {})

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

    # Get all current clients
    current_clients = Contact.objects.filter(client_status="Current").order_by("name")

    # Build client data
    client_data = []
    for client in current_clients:
        # Get total time entries for this client's matters with optional date filtering
        time_entries = TimeEntry.objects.filter(matter__client=client)
        if date_from_obj:
            time_entries = time_entries.filter(date__gte=date_from_obj)
        if date_to_obj:
            time_entries = time_entries.filter(date__lte=date_to_obj)
        total_hours = time_entries.aggregate(Sum("hours"))["hours__sum"] or 0
        total_fees = sum(entry.fee for entry in time_entries)

        # Get total invoices for this client's matters with optional date filtering
        invoices = Invoice.objects.filter(
            matter__client=client, status__in=["SENT", "PAID"]
        )
        if date_from_obj:
            invoices = invoices.filter(date_issued__gte=date_from_obj)
        if date_to_obj:
            invoices = invoices.filter(date_issued__lte=date_to_obj)
        total_invoices = sum(invoice.value["final_total"] for invoice in invoices)

        # Get total payments for this client's matters with optional date filtering
        payments = Payment.objects.filter(matter__client=client)
        if date_from_obj:
            payments = payments.filter(date__gte=date_from_obj)
        if date_to_obj:
            payments = payments.filter(date__lte=date_to_obj)
        total_payments = payments.aggregate(Sum("amount"))["amount__sum"] or 0

        client_data.append(
            {
                "client": client,
                "client_name": client.name,  # For sorting
                "total_hours": total_hours,
                "total_fees": total_fees,
                "total_invoices": total_invoices,
                "total_payments": total_payments,
                "time_entries_count": time_entries.count(),
                "invoices_count": invoices.count(),
                "payments_count": payments.count(),
            }
        )

    # Sort the data
    reverse_sort = sort_direction == "desc"
    if sort_by == "client_name":
        client_data.sort(key=lambda x: x["client_name"].lower(), reverse=reverse_sort)
    else:
        client_data.sort(key=lambda x: x[sort_by], reverse=reverse_sort)

    context = {
        "app": "reports",
        "subapp": "clients",
        "client_data": client_data,
        "current_sort": sort_by,
        "current_direction": sort_direction,
        "date_from": date_from,
        "date_to": date_to,
    }

    return render(request, "reports/clients/main.html", context)


@login_required
@staff_member_required
def clients_list(request):
    # Get sorting parameters
    sort_by = request.GET.get("sort", "client_name")
    sort_direction = request.GET.get("direction", "asc")

    # Get filter data from session
    filter_data = request.session.get("clients_filter", {})

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

    # Get all current clients
    current_clients = Contact.objects.filter(client_status="Current").order_by("name")

    # Build client data
    client_data = []
    for client in current_clients:
        # Get total time entries for this client's matters with optional date filtering
        time_entries = TimeEntry.objects.filter(matter__client=client)
        if date_from_obj:
            time_entries = time_entries.filter(date__gte=date_from_obj)
        if date_to_obj:
            time_entries = time_entries.filter(date__lte=date_to_obj)
        total_hours = time_entries.aggregate(Sum("hours"))["hours__sum"] or 0
        total_fees = sum(entry.fee for entry in time_entries)

        # Get total invoices for this client's matters with optional date filtering
        invoices = Invoice.objects.filter(
            matter__client=client, status__in=["SENT", "PAID"]
        )
        if date_from_obj:
            invoices = invoices.filter(date_issued__gte=date_from_obj)
        if date_to_obj:
            invoices = invoices.filter(date_issued__lte=date_to_obj)
        total_invoices = sum(invoice.value["final_total"] for invoice in invoices)

        # Get total payments for this client's matters with optional date filtering
        payments = Payment.objects.filter(matter__client=client)
        if date_from_obj:
            payments = payments.filter(date__gte=date_from_obj)
        if date_to_obj:
            payments = payments.filter(date__lte=date_to_obj)
        total_payments = payments.aggregate(Sum("amount"))["amount__sum"] or 0

        client_data.append(
            {
                "client": client,
                "client_name": client.name,  # For sorting
                "total_hours": total_hours,
                "total_fees": total_fees,
                "total_invoices": total_invoices,
                "total_payments": total_payments,
                "time_entries_count": time_entries.count(),
                "invoices_count": invoices.count(),
                "payments_count": payments.count(),
            }
        )

    # Sort the data
    reverse_sort = sort_direction == "desc"
    if sort_by == "client_name":
        client_data.sort(key=lambda x: x["client_name"].lower(), reverse=reverse_sort)
    else:
        client_data.sort(key=lambda x: x[sort_by], reverse=reverse_sort)

    context = {
        "app": "reports",
        "subapp": "clients",
        "client_data": client_data,
        "current_sort": sort_by,
        "current_direction": sort_direction,
        "date_from": date_from,
        "date_to": date_to,
    }

    return render(request, "reports/clients/list.html", context)


@login_required
@staff_member_required
def clients_filter(request):
    filter_manager = FilterManager(request, ClientReportFilter, "clients_filter")

    if filter_manager.process_filter():
        return HttpResponse(status=204, headers={"HX-Trigger": "clientsChanged"})

    # Get current filter data from session for display
    filter_data = request.session.get("clients_filter", {})

    return render(request, "reports/clients/filter.html", {"filter_data": filter_data})


@login_required
@staff_member_required
def client_statement_filter(request):
    if request.method == "POST":
        # Convert month/year inputs to date_from and date_to
        month_num = request.POST.get("month_num")
        year_str = request.POST.get("year")
        client_id = request.POST.get("client")

        filter_data = {}

        if client_id:
            filter_data["client"] = client_id

        if month_num and year_str:
            import calendar

            month = int(month_num)
            year = int(year_str)

            # Get first day of month
            first_day = datetime(year, month, 1).date()

            # Get last day of month
            last_day_num = calendar.monthrange(year, month)[1]
            last_day = datetime(year, month, last_day_num).date()

            filter_data["date_from"] = first_day.strftime("%Y-%m-%d")
            filter_data["date_to"] = last_day.strftime("%Y-%m-%d")
            filter_data["month_num"] = month_num
            filter_data["year"] = year_str

        request.session["client_statement_filter"] = filter_data

        return HttpResponse(
            status=204, headers={"HX-Trigger": "clientStatementChanged"}
        )

    # Get current filter data from session for display
    filter_data = request.session.get("client_statement_filter", {})
    clients = Contact.objects.filter(client_status="Current").order_by("name")

    # Generate year list (5 years back, current year, 2 years forward)
    current_year = datetime.now().year
    years = range(current_year - 5, current_year + 3)

    return render(
        request,
        "reports/clients/statement_filter.html",
        {"filter_data": filter_data, "clients": clients, "years": years},
    )


@login_required
@staff_member_required
def client_statement(request):

    # Get current filter data from session
    filter_data = request.session.get("client_statement_filter", {})

    client_id = filter_data.get("client")
    date_from = filter_data.get("date_from")
    date_to = filter_data.get("date_to")

    client = None
    matters_data = []

    if client_id:
        try:
            client = Contact.objects.get(id=client_id)

            # Get time entries
            time_entries = TimeEntry.objects.filter(matter__client=client).order_by(
                "matter__name", "-date", "-id"
            )
            if date_from:
                time_entries = time_entries.filter(date__gte=date_from)
            if date_to:
                time_entries = time_entries.filter(date__lte=date_to)

            # Get expense entries
            expense_entries = ExpenseEntry.objects.filter(
                matter__client=client
            ).order_by("matter__name", "-date", "-id")
            if date_from:
                expense_entries = expense_entries.filter(date__gte=date_from)
            if date_to:
                expense_entries = expense_entries.filter(date__lte=date_to)

            # Group entries by matter
            from collections import defaultdict

            matters_dict = defaultdict(
                lambda: {"time_entries": [], "expense_entries": []}
            )

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
            for matter_id, data in matters_dict.items():
                matter_time_entries = data["time_entries"]
                matter_expense_entries = data["expense_entries"]

                matters_data.append(
                    {
                        "matter": data["matter"],
                        "time_entries": matter_time_entries,
                        "expense_entries": matter_expense_entries,
                        "total_hours": sum(
                            entry.hours for entry in matter_time_entries
                        ),
                        "total_fees": sum(entry.fee for entry in matter_time_entries),
                        "total_expenses": sum(
                            entry.amount for entry in matter_expense_entries
                        ),
                    }
                )

            # Sort matters by name
            matters_data.sort(key=lambda x: x["matter"].name)

        except Contact.DoesNotExist:
            pass

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
        "app": "reports",
        "subapp": "client-statement",
        "client": client,
        "matters_data": matters_data,
        "filter_data": filter_data,
        "time_entries_count": time_entries_count,
        "expense_entries_count": expense_entries_count,
        "total_hours": total_hours,
        "total_fees": total_fees,
        "total_expenses": total_expenses,
        "is_cb_client": is_cb_client,
        "prepayment": prepayment,
        "amount_due": amount_due,
    }

    # Return partial template for HTMX requests
    if request.headers.get("HX-Request"):
        return render(request, "reports/clients/statement_content.html", context)

    return render(request, "reports/clients/statement.html", context)


@login_required
@staff_member_required
def client_statement_pdf(request):
    """Export client statement report as PDF"""

    # Get current filter data from session
    filter_data = request.session.get("client_statement_filter", {})

    client_id = filter_data.get("client")
    date_from = filter_data.get("date_from")
    date_to = filter_data.get("date_to")

    if not client_id:
        return HttpResponse("No client selected", status=400)

    try:
        client = Contact.objects.get(id=client_id)
    except Contact.DoesNotExist:
        return HttpResponse("Client not found", status=404)

    # Convert date strings to date objects if provided
    date_from_obj = None
    date_to_obj = None

    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, "%Y-%m-%d").date()
        except ValueError:
            pass

    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, "%Y-%m-%d").date()
        except ValueError:
            pass

    # Generate PDF
    pdf_file = generate_client_statement_pdf(
        client, date_from_obj, date_to_obj, request
    )

    # Create response
    with open(pdf_file.name, "rb") as f:
        response = HttpResponse(f.read(), content_type="application/pdf")

    # Set filename for download
    filename = f"{client.name}_activity_report_{datetime.now().strftime('%Y%m%d')}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    return response
