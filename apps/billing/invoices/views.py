import os
from datetime import datetime
from itertools import chain

from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.matters.models import Matter

from .filters import InvoiceFilter
from .forms import EditInvoiceForm, InvoiceForm
from .functions import generate_invoice
from .functions.calculate_inv_amount import calculate_inv_amount
from .models import Invoice


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

    page = request.GET.get("page")
    pagination = Paginator(invoices, per_page=10).get_page(page)

    context = {
        "page": "billing",
        "subpage": "invoices",
        "pagination": pagination,
        "objects": pagination.object_list,
    }

    return render(request, "billing/invoices/list.html", context)


@login_required
def invoices_detail(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    context = {
        "page": "billing",
        "file_url": reverse_lazy("billing:invoice-pdf", kwargs={"pk": invoice.pk}),
        "invoice": invoice,
    }

    return render(request, "billing/invoices/preview/preview.html", context)


@login_required
def invoices_add(request):
    if request.method == "POST":
        form = InvoiceForm(request.POST)

        if form.is_valid():
            invoice = form.save(commit=False)

            invoice.created_by = request.user
            invoice.save()

            calc = calculate_inv_amount(invoice)
            invoice.amount = calc["invoice_total"]

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
            form.save()

            date_limit = form.cleaned_data["date_limit"]

            TimeEntry.objects.filter(invoice=invoice, date__gt=date_limit).update(
                invoice=None
            )

            ExpenseEntry.objects.filter(invoice=invoice, date__gt=date_limit).update(
                invoice=None
            )

            time_entry_amount = (
                TimeEntry.objects.filter(invoice=invoice)
                .annotate(
                    fee=ExpressionWrapper(
                        F("hours") * F("rate"), output_field=DecimalField()
                    )
                )
                .aggregate(total_fee=Sum("fee"))["total_fee"]
            ) or 0

            expense_amount = (
                ExpenseEntry.objects.filter(invoice=invoice).aggregate(
                    total_amount=Sum("amount")
                )["total_amount"]
                or 0
            )

            invoice.amount = (time_entry_amount + expense_amount) - invoice.discount
            invoice.save()

            return redirect("billing:invoices-detail", pk=pk)
    else:
        form = EditInvoiceForm(instance=invoice)

    return render(
        request, "billing/invoices/edit.html", {"form": form, "invoice": invoice}
    )


@login_required
def invoices_delete(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    invoice.delete()

    return redirect("billing:invoices-list")


@login_required
def invoices_cancel(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    return render(request, "billing/invoices/confirm-cancel.html", {"invoice": invoice})


@login_required
def invoices_pdf(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    if invoice.status == "CANCELED":
        with open(invoice.pdf_file.path, "rb") as pdf:
            response = HttpResponse(pdf.read(), content_type="application/pdf")
            response["Content-Disposition"] = (
                f'filename="Invoice {invoice.id} - {invoice.matter} - {invoice.date_issued}.pdf"'
            )
    else:
        file = generate_invoice(invoice, request)

        with open(file.name, "rb") as pdf:
            response = HttpResponse(pdf.read(), content_type="application/pdf")
            response["Content-Disposition"] = (
                f'filename="Invoice {invoice.id} - {invoice.matter} - {invoice.date_issued}.pdf"'
            )

        os.unlink(file.name)

    return response


@login_required
def invoices_status_update(request, pk):
    if request.method == "POST":
        invoice = get_object_or_404(Invoice, pk=pk)

        invoice_status = request.POST["status"]
        invoice.status = invoice_status

        if invoice_status == "APPROVED":
            invoice.date_approved = datetime.now()
        elif invoice_status == "SENT":
            invoice.date_sent = datetime.now()
        elif invoice_status == "CANCELED":
            invoice.date_canceled = datetime.now()

        invoice.save()

        if invoice_status == "CANCELED":
            pdf_file = generate_invoice(invoice, request)

            with open(pdf_file.name, "rb") as pdf:
                invoice.pdf_file.save(
                    f"Invoice {invoice.id} - {invoice.matter} - {invoice.date_issued}.pdf",
                    ContentFile(pdf.read()),
                )
            invoice.save()

            TimeEntry.objects.filter(invoice=invoice).update(invoice=None)

            ExpenseEntry.objects.filter(invoice=invoice).update(invoice=None)

            return redirect("billing:invoices-list")

        return render(request, "billing/invoices/row.html", {"invoice": invoice})


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
