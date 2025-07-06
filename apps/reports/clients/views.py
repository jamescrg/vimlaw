from datetime import datetime

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import render

from apps.activity.time.models import TimeEntry
from apps.contacts.models import Contact
from apps.invoicing.invoices.models import Invoice
from apps.invoicing.payments.models import Payment
from apps.management.filter_manager import FilterManager

from .filters import ClientReportFilter


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
