import os
from itertools import chain

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.generic import DeleteView, DetailView, FormView

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


class NewInvoiceView(LoginRequiredMixin, FormView):
    template_name = "invoicing/new-invoice.html"
    form_class = InvoiceForm
    success_url = reverse_lazy("invoicing:invoicing")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        form = self.form_class()

        entries = TimeEntry.objects.filter(invoice__isnull=True, entered=0).values_list(
            "matter", flat=True
        )
        expenses = ExpenseEntry.objects.filter(
            invoice__isnull=True, entered=0
        ).values_list("matter", flat=True)

        matter_list = (
            Matter.objects.filter(status="Open", id__in=chain(entries, expenses))
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
            response["Content-Disposition"] = f'filename="{invoice}.pdf"'

        os.unlink(file.name)

        return response
