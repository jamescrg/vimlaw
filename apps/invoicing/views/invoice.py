import os
from itertools import chain
from tempfile import NamedTemporaryFile

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.base import ContentFile
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.views.generic import FormView
from weasyprint import HTML

from apps.activity.models import ExpenseEntry, TimeEntry
from apps.invoicing.forms import InvoiceForm
from apps.invoicing.models import Invoice
from apps.matters.models import Matter
from config.settings import BASE_DIR


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

        if invoice.show_comp:
            entries = TimeEntry.objects.filter(
                matter=invoice.matter,
                date__range=[invoice.date_from, invoice.date_to],
                invoice=invoice,
            )
        else:
            entries = TimeEntry.objects.filter(
                matter=invoice.matter,
                date__range=[invoice.date_from, invoice.date_to],
                invoice=invoice,
                comp=invoice.show_comp,
            )

        entries_total = (
            entries.annotate(
                fee=ExpressionWrapper(
                    F("hours") * F("firm_rate"), output_field=DecimalField()
                )
            ).aggregate(total_fee=Sum("fee"))["total_fee"]
        ) or 0

        if invoice.show_comp:
            expenses = ExpenseEntry.objects.filter(
                matter=invoice.matter,
                date__range=[invoice.date_from, invoice.date_to],
                invoice=invoice,
            )
        else:
            expenses = ExpenseEntry.objects.filter(
                matter=invoice.matter,
                date__range=[invoice.date_from, invoice.date_to],
                invoice=invoice,
                comp=invoice.show_comp,
            )
        expenses_total = (
            expenses.aggregate(total_amount=Sum("amount"))["total_amount"] or 0
        )

        pre_discount_total = entries_total + expenses_total
        combined_total = pre_discount_total * (1 - invoice.discount / 100)

        context = {
            "invoice": invoice,
            "entries": entries,
            "expenses": expenses,
            "entries_total": entries_total,
            "expenses_total": expenses_total,
            "combined_total": combined_total,
            "pre_discount_total": pre_discount_total,
        }

        html_string = render_to_string("invoicing/invoice.html", context)
        html = HTML(string=html_string, base_url=self.request.build_absolute_uri())

        with NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
            html.write_pdf(
                target=pdf_file.name,
                stylesheets=[
                    BASE_DIR.joinpath(
                        os.path.join("static", "css", "invoice_template.css")
                    )
                ],
            )
            pdf_file.seek(0)

            invoice.pdf_file.save(
                f"{invoice.matter.name}_{invoice.issue_date}_{invoice.id}.pdf",
                ContentFile(pdf_file.read()),
            )

        invoice.save()

        return super().form_valid(form)
