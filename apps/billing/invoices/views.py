import os
from itertools import chain

from django.contrib.auth.decorators import login_required
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
from apps.billing.invoices.get_invoice_data import get_invoice_data
from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter

from .filters import InvoiceFilter
from .forms import EditInvoiceForm, InvoiceForm
from .functions import generate_invoice
from .models import Invoice


@login_required
def invoices_index(request):
    invoice_data = get_invoice_data(request)

    context = {
        "app": "billing",
        "subapp": "invoices",
    } | invoice_data

    return render(request, "billing/invoices/main.html", context)


@login_required
def invoices_list(request):
    invoice_data = get_invoice_data(request)

    context = {
        "app": "billing",
        "subapp": "invoices",
    }

    context = context | invoice_data

    return render(request, "billing/invoices/list.html", context)


@login_required
def invoices_detail_index(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "billing",
        "subapp": "preview",
        "invoice": invoice,
    }

    return render(request, "billing/invoices/detail-index.html", context)


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
def pdf_preview_index(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "billing",
        "subapp": "preview",
        "invoice": invoice,
    }

    return render(request, "billing/invoices/preview/index.html", context)


@login_required
def pdf_preview(request, pk):
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

    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key="invoice_time_pagination"
    )

    context = {
        "app": "billing",
        "subapp": "time",
        "objects": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "invoice_time_pagination",
        "trigger_key": "timeChanged",
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

    pagination = CustomPaginator(
        expenses,
        per_page=10,
        request=request,
        session_key="invoice_expenses_pagination",
    )

    context = {
        "app": "billing",
        "subapp": "expenses",
        "objects": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "invoice_expenses_pagination",
        "trigger_key": "expensesChanged",
        "invoice": invoice,
        "summary": summary,
    }

    return render(request, "billing/invoices/expenses/list.html", context)


@login_required
def invoices_add(request):
    if request.method == "POST":
        form = InvoiceForm(request.POST, use_required_attribute=False)
        if form.is_valid():
            invoice = form.save(commit=False)
            invoice.created_by = request.user
            invoice.save()

            filter_data = request.session.get("invoices_filter", {})
            filter_data["status"] = "DRAFT"
            request.session["invoices_filter"] = filter_data
            return HttpResponse(status=204, headers={"HX-Trigger": "invoicesChanged"})

    else:
        form = InvoiceForm(use_required_attribute=False)

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
        form = EditInvoiceForm(
            request.POST, instance=invoice, use_required_attribute=False
        )
        if form.is_valid():
            invoice.save()

            return redirect("billing:invoice-time-entries-index", pk=pk)

    else:
        form = EditInvoiceForm(instance=invoice, use_required_attribute=False)

    context = {"form": form, "invoice": invoice}

    return render(request, "billing/invoices/edit.html", context)


@login_required
def invoices_delete(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    invoice.delete()

    return redirect("billing:invoices-index")


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

        return HttpResponse(status=204, headers={"HX-Trigger": "invoicesChanged"})
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

    return HttpResponse(status=204, headers={"HX-Trigger": "invoicesChanged"})


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

    return HttpResponse(status=204, headers={"HX-Trigger": "invoicesChanged"})


@login_required
def invoices_edit_status(request, pk, status):
    invoice = get_object_or_404(Invoice, pk=pk)
    invoice.status = status
    invoice.save()
    context = {"invoice": invoice}
    return render(request, "billing/invoices/status.html", context)
