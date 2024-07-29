import os
from datetime import datetime
from itertools import chain

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.generic import DeleteView, DetailView, FormView, View

from apps.activity.models import ExpenseEntry, TimeEntry
from apps.invoicing.forms import InvoiceForm
from apps.invoicing.functions import generate_invoice
from apps.invoicing.models import Invoice
from apps.matters.models import Matter


@login_required
def index(request):
    invoices = (
        Invoice.objects.all()
        .select_related("matter", "created_by")
        .order_by("-created_at")
    )

    context = {
        "page": "invoicing",
        "invoices": invoices,
    }

    return render(request, "invoicing/list.html", context)


class InvoiceDetailView(LoginRequiredMixin, DetailView):
    model = Invoice
    template_name = "invoicing/preview/preview.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["page"] = "invoicing"

        context["file_url"] = reverse_lazy(
            "invoicing:invoice-pdf", kwargs={"pk": self.object.pk}
        )

        return context


class AddInvoiceView(LoginRequiredMixin, FormView):
    template_name = "invoicing/form-invoice.html"
    form_class = InvoiceForm
    success_url = reverse_lazy("invoicing:invoicing")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        form = self.form_class()

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

        context["form"] = form

        return context

    def form_valid(self, form):
        invoice = form.save(commit=False)
        invoice.created_by = self.request.user

        invoice.save()

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

        return super().form_valid(form)


class DeleteInvoiceView(LoginRequiredMixin, DeleteView):
    model = Invoice
    success_url = reverse_lazy("invoicing:invoicing")

    def get(self, request, *args, **kwargs):
        return self.delete(request, *args, **kwargs)


class InvoicePDFView(LoginRequiredMixin, DetailView):
    model = Invoice

    def get(self, request, *args, **kwargs):
        invoice = self.get_object()

        file = generate_invoice(invoice, request)

        with open(file.name, "rb") as pdf:
            response = HttpResponse(pdf.read(), content_type="application/pdf")
            response["Content-Disposition"] = (
                f'filename="Invoice {invoice.id} - {invoice.matter} - {invoice.date_issued}.pdf"'
            )

        os.unlink(file.name)

        return response


class StatusUpdateView(LoginRequiredMixin, View):
    model = Invoice

    def post(self, request, *args, **kwargs):
        invoice = self.model.objects.get(pk=kwargs["pk"])

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
            TimeEntry.objects.filter(invoice=invoice).update(invoice=None)
            ExpenseEntry.objects.filter(invoice=invoice).update(invoice=None)

        return render(request, "invoicing/invoice-row.html", {"invoice": invoice})
