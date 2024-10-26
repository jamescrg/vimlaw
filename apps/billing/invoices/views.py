import os
from itertools import chain

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.expenses.summary import (
    calculate_summary as calculate_expense_summary,
)
from apps.activity.time.models import TimeEntry
from apps.activity.time.summary import calculate_summary as calculate_time_summary
from apps.billing.invoices.functions import generate_ledes_98b
from apps.matters.models import Matter

from .filters import InvoiceFilter
from .forms import EditInvoiceForm, InvoiceForm
from .functions import generate_invoice
from .models import INVOICE_STATUS, Invoice


@login_required
def invoices_list(request):
    filter_data = request.session.get("invoices_filter", None)

    if filter_data:
        filter = InvoiceFilter(filter_data)
        invoices = filter.qs
    else:
        invoices = (
            Invoice.objects.all()
            .select_related("matter", "created_by")
            .order_by("-created_at")
        )

    total_fees = sum(invoice.value["net_fees"] for invoice in invoices)
    total_expenses = sum(invoice.value["net_expenses"] for invoice in invoices)
    total = total_fees + total_expenses

    page = request.GET.get("page")
    pagination = Paginator(invoices, per_page=10).get_page(page)

    selected_status = filter_data.get("status", "") if filter_data else ""

    context = {
        "app": "billing",
        "subapp": "invoices",
        "pagination": pagination,
        "objects": pagination.object_list,
        "total_fees": total_fees,
        "total_expenses": total_expenses,
        "total": total,
        "status_options": INVOICE_STATUS,
        "selected_status": selected_status,
    }

    return render(request, "billing/invoices/list.html", context)


@login_required
def invoices_detail(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "billing",
        "subapp": "preview",
        "file_url": reverse_lazy("billing:invoices-pdf", kwargs={"pk": invoice.pk}),
        "invoice": invoice,
    }
    return render(request, "billing/invoices/preview/preview.html", context)


@login_required
def invoice_time_entires_index(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "billing",
        "subapp": "time",
        "invoice": invoice,
    }

    return render(request, "billing/invoices/time/index.html", context)


@login_required
def invoice_time_entires(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    entries = TimeEntry.objects.filter(invoice=invoice).order_by("date")
    summary = calculate_time_summary(entries)

    page = request.GET.get("page")
    pagination = Paginator(entries, per_page=10).get_page(page)

    context = {
        "app": "billing",
        "subapp": "time",
        "objects": pagination.object_list,
        "pagination": pagination,
        "invoice": invoice,
        "summary": summary,
    }

    return render(request, "billing/invoices/time/list.html", context)


@login_required
def invoice_expense_entries_index(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "billing",
        "subapp": "expenses",
        "invoice": invoice,
    }

    return render(request, "billing/invoices/expenses/index.html", context)


@login_required
def invoice_expense_entries(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    expenses = ExpenseEntry.objects.filter(invoice=invoice).order_by("date")
    summary = calculate_expense_summary(expenses)

    page = request.GET.get("page")
    pagination = Paginator(expenses, per_page=10).get_page(page)

    context = {
        "app": "billing",
        "subapp": "expenses",
        "objects": pagination.object_list,
        "pagination": pagination,
        "invoice": invoice,
        "summary": summary,
    }

    return render(request, "billing/invoices/expenses/list.html", context)


@login_required
def invoices_add(request):
    if request.method == "POST":
        form = InvoiceForm(request.POST)
        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.created_by = request.user
            invoice.save()
            return redirect("billing:invoices-list")

    else:
        form = InvoiceForm()

        entries = TimeEntry.objects.filter(
            invoice__isnull=True, entered=0, date__gte="2024-01-01"
        ).values_list("matter", flat=True)

        expenses = ExpenseEntry.objects.filter(
            invoice__isnull=True, entered=0
        ).values_list("matter", flat=True)

        matter_list = (
            Matter.objects.filter(id__in=chain(entries, expenses))
            .distinct()
            .order_by("name")
        )
        form.fields["matter"].queryset = matter_list

    return render(request, "billing/invoices/form.html", {"form": form})


@login_required
def invoices_edit(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    if request.method == "POST":
        form = EditInvoiceForm(request.POST, instance=invoice)
        if form.is_valid():
            invoice.save()
            return redirect("billing:invoice-time-entries", pk=pk)
    else:
        form = EditInvoiceForm(instance=invoice)
    context = {"form": form, "invoice": invoice}
    return render(request, "billing/invoices/edit.html", context)


@login_required
def invoices_delete(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    invoice.delete()
    return redirect("billing:invoices-list")


@login_required
def invoices_pdf(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    file = generate_invoice(invoice, request)
    notation = "DRAFT - " if invoice.status == "DRAFT" else ""

    with open(file.name, "rb") as pdf:
        response = HttpResponse(pdf.read(), content_type="application/pdf")
        filename = f'filename="{notation}Invoice {invoice.id} - {invoice.matter} - {invoice.date_issued}.pdf"'
        response["Content-Disposition"] = filename
    os.unlink(file.name)

    return response


@login_required
def invoice_ledes_98b(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    ledes_file = generate_ledes_98b(invoice)

    with open(ledes_file.name, "rb") as file:
        response = HttpResponse(file.read(), content_type="text/plain")

        filename = f'attachment; filename="LEDES98B - {invoice.id} - {invoice.matter} - {invoice.date_issued}.txt"'
        response["Content-Disposition"] = filename

    os.unlink(ledes_file.name)

    return response


@login_required
def invoices_filter(request):
    if request.method == "POST":
        request.session["invoices_filter"] = request.POST

        return redirect("billing:invoices-list")
    else:
        filter_data = request.session.get("invoices_filter", {})

        filter = InvoiceFilter(
            filter_data,
            queryset=Invoice.objects.all()
            .select_related("matter", "created_by")
            .order_by("-created_at"),
        )

        return render(request, "billing/invoices/filter.html", {"filter": filter})


@login_required
def invoices_filter_status(request, status):
    filter_data = request.session.get("invoices_filter", {})
    filter_data["status"] = status

    request.session["invoices_filter"] = filter_data

    return redirect("billing:invoices-list")


@login_required
def order_by_invoices(request, order):
    filter_data = request.session.get("invoices_filter", {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["invoices_filter"] = filter_data

    return redirect("billing:invoices-list")


@login_required
def invoices_edit_status(_, pk, status):
    invoice = get_object_or_404(Invoice, pk=pk)

    invoice.status = status
    invoice.save()

    return redirect("billing:invoices-list")
