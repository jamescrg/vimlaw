import os
from datetime import datetime
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
from apps.invoicing.invoices.functions import generate_ledes_98b
from apps.invoicing.invoices.get_invoice_data import get_invoice_data
from apps.invoicing.payments.forms import PaymentForm
from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter
from apps.trust.models import Transaction

from .filters import InvoiceFilter
from .forms import EditInvoiceForm, InvoiceForm
from .functions import generate_invoice
from .models import Invoice


@login_required
def invoices_index(request):
    invoice_data = get_invoice_data(request)

    context = {
        "app": "invoicing",
        "subapp": "invoices",
        "view": "list",
    } | invoice_data

    return render(request, "invoicing/invoices/main.html", context)


@login_required
def invoices_list(request):
    invoice_data = get_invoice_data(request)

    context = {
        "app": "invoicing",
        "subapp": "invoices",
        "view": "list",
    }

    context = context | invoice_data

    return render(request, "invoicing/invoices/list.html", context)


@login_required
def invoices_detail_index(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "invoicing",
        "subapp": "time",
        "invoice": invoice,
        "view": "detail",
    }

    return render(request, "invoicing/invoices/detail/detail-index.html", context)


@login_required
def invoices_detail(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "invoicing",
        "subapp": "time",
        "invoice": invoice,
        "view": "detail",
    }

    return render(request, "invoicing/invoices/time/index.html", context)


@login_required
def invoice_details_index(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "invoicing",
        "subapp": "details",
        "invoice": invoice,
        "view": "detail",
    }

    return render(request, "invoicing/invoices/detail/details.html", context)


@login_required
def pdf_preview_index(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "invoicing",
        "subapp": "preview",
        "file_url": reverse_lazy("invoicing:invoices-pdf", kwargs={"pk": invoice.pk}),
        "invoice": invoice,
        "view": "detail",
    }

    return render(request, "invoicing/invoices/preview/index.html", context)


@login_required
def pdf_preview(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "app": "invoicing",
        "subapp": "preview",
        "file_url": reverse_lazy("invoicing:invoices-pdf", kwargs={"pk": invoice.pk}),
        "invoice": invoice,
        "view": "detail",
    }

    return render(request, "invoicing/invoices/preview/preview.html", context)


@login_required
def invoice_time_entries_index(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    entries = TimeEntry.objects.filter(invoice=invoice).order_by("date")
    summary = calculate_time_summary(entries)

    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key="invoice_time_pagination"
    )

    context = {
        "app": "invoicing",
        "subapp": "time",
        "objects": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "invoice_time_pagination",
        "trigger_key": "timeChanged",
        "invoice": invoice,
        "summary": summary,
        "view": "detail",
    }

    return render(request, "invoicing/invoices/time/index.html", context)


@login_required
def invoice_time_entries(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    entries = TimeEntry.objects.filter(invoice=invoice).order_by("date")
    summary = calculate_time_summary(entries)

    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key="invoice_time_pagination"
    )

    context = {
        "app": "invoicing",
        "subapp": "time",
        "objects": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "invoice_time_pagination",
        "trigger_key": "timeChanged",
        "invoice": invoice,
        "summary": summary,
        "view": "detail",
    }

    return render(request, "invoicing/invoices/time/list.html", context)


@login_required
def invoice_expense_entries_index(request, pk):
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
        "app": "invoicing",
        "subapp": "expenses",
        "objects": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "invoice_expenses_pagination",
        "trigger_key": "expensesChanged",
        "invoice": invoice,
        "summary": summary,
        "view": "detail",
    }

    return render(request, "invoicing/invoices/expenses/index.html", context)


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
        "app": "invoicing",
        "subapp": "expenses",
        "objects": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "invoice_expenses_pagination",
        "trigger_key": "expensesChanged",
        "invoice": invoice,
        "summary": summary,
        "view": "detail",
    }

    return render(request, "invoicing/invoices/expenses/list.html", context)


@login_required
def quick_invoice_payment(request, pk, payment_type):
    current_date = datetime.now().date()

    try:
        invoice = Invoice.objects.get(pk=pk)
    except (Invoice.DoesNotExist, Exception):
        return HttpResponse(status=404)
    invoice_value = invoice.value["final_total"]

    form = PaymentForm(
        request.POST or None,
        use_required_attribute=False,
        initial={
            "amount": invoice_value,
            "matter": invoice.matter,
            "detail": f"Invoice {invoice.id}",
        },
    )

    if payment_type == "trust":
        form.fields["payment_method"].initial = "TRUST"

    if request.method == "POST" and form.is_valid():
        payment = form.save()

        if payment.amount == invoice_value:
            invoice.status = "PAID"
            invoice.save()

        if payment_type == "trust":
            Transaction.objects.create(
                contact=invoice.matter.client,
                date=current_date,
                type="Withdrawal",
                amount=payment.amount,
                description=f"Invoice {invoice.id}",
            )

        return HttpResponse(status=302, headers={"HX-Redirect": "/invoicing/payments"})

    return render(
        request,
        "invoicing/invoices/quick-pay-form.html",
        {"form": form, "invoice": invoice, "payment_type": payment_type},
    )


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

        # Create a list of matters with unbilled time for the dropdown
        matters_with_unbilled = []
        for matter in matter_list:
            unbilled_amount = matter.value["unbilled"]["net_fees_and_expenses"]
            matters_with_unbilled.append(
                (matter.id, f"{matter.name}\u00A0\u00A0\u00A0(${unbilled_amount:,.2f})")
            )

        form.fields["matter"].queryset = matter_list
        form.fields["matter"].widget.choices = matters_with_unbilled

    return render(request, "invoicing/invoices/form.html", {"form": form})


@login_required
def invoices_edit(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    if request.method == "POST":
        form = EditInvoiceForm(
            request.POST, instance=invoice, use_required_attribute=False
        )
        if form.is_valid():
            invoice.save()

            return HttpResponse(
                status=204, headers={"HX-Trigger": "invoiceDetailChanged"}
            )

    else:
        form = EditInvoiceForm(instance=invoice, use_required_attribute=False)

    context = {"form": form, "invoice": invoice}

    return render(request, "invoicing/invoices/edit.html", context)


@login_required
def invoices_delete(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    invoice.delete()

    return redirect("invoicing:invoices-index")


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
def invoices_pdf_download(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    file = generate_invoice(invoice, request)

    notation = "DRAFT - " if invoice.status == "DRAFT" else ""

    with open(file.name, "rb") as pdf:
        response = HttpResponse(pdf.read(), content_type="application/pdf")
        filename = f'filename="{notation}Invoice {invoice.id} - {invoice.matter} - {invoice.date_issued}.pdf"'
        response["Content-Disposition"] = f"attachment; {filename}"

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

        if filter_data:
            filter = InvoiceFilter(
                filter_data,
                queryset=Invoice.objects.all()
                .select_related("matter", "created_by")
                .order_by("-created_at"),
            )
        else:
            default_filter = {"order_by": "-date_issued"}

            filter = InvoiceFilter(
                default_filter,
                queryset=Invoice.objects.all()
                .select_related("matter", "created_by")
                .order_by("-created_at"),
            )
        return render(request, "invoicing/invoices/filter.html", {"filter": filter})


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
def invoices_edit_status(_, pk, status, view):
    invoice = get_object_or_404(Invoice, pk=pk)

    invoice.status = status
    invoice.save()

    trigger = "invoicesChanged" if view == "list" else "invoiceDetailChanged"

    return HttpResponse(status=204, headers={"HX-Trigger": trigger})
