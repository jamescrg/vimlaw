import os
from tempfile import NamedTemporaryFile

from django.core.handlers.wsgi import WSGIRequest
from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.template.loader import render_to_string
from weasyprint import HTML

from apps.activity.models import ExpenseEntry, TimeEntry
from apps.invoicing.models import Invoice
from config.settings import BASE_DIR


def generate_invoice(invoice: Invoice, request: WSGIRequest) -> NamedTemporaryFile:
    """
    Generate a PDF invoice for the given invoice instance
    """

    if invoice.show_comp:
        entries = TimeEntry.objects.filter(
            invoice=invoice,
        ).order_by("date")
    else:
        entries = TimeEntry.objects.filter(
            invoice=invoice,
            comp=invoice.show_comp,
        ).order_by("date")

    # total fees prior to any comp hours
    entries_gross_total = (
        entries.annotate(
            fee=ExpressionWrapper(
                F("hours") * F("firm_rate"), output_field=DecimalField()
            )
        ).aggregate(total_fee=Sum("fee"))["total_fee"]
    ) or 0

    # total fees for comp hours
    entries_comp_total = (
        entries.filter(comp=1)
        .annotate(
            fee=ExpressionWrapper(
                F("hours") * F("firm_rate"), output_field=DecimalField()
            )
        )
        .aggregate(total_fee=Sum("fee"))["total_fee"]
    ) or 0

    # net fees after comp hours
    entries_net_total = entries_gross_total - entries_comp_total

    if invoice.show_comp:
        expenses = ExpenseEntry.objects.filter(
            invoice=invoice,
        ).order_by("date")
    else:
        expenses = ExpenseEntry.objects.filter(
            invoice=invoice,
            comp=invoice.show_comp,
        ).order_by("date")

    expenses_gross_total = (
        expenses.aggregate(total_amount=Sum("amount"))["total_amount"] or 0
    )
    expenses_comp_total = (
        expenses.filter(comp=1).aggregate(total_amount=Sum("amount"))["total_amount"]
        or 0
    )
    expenses_net_total = expenses_gross_total - expenses_comp_total

    pre_discount_total = entries_net_total + expenses_net_total
    invoice_total = pre_discount_total - invoice.discount

    context = {
        "invoice": invoice,
        "entries": entries,
        "expenses": expenses,
        "entries_gross_total": entries_gross_total,
        "entries_comp_total": entries_comp_total,
        "entries_net_total": entries_net_total,
        "expenses_gross_total": expenses_gross_total,
        "expenses_comp_total": expenses_comp_total,
        "expenses_net_total": expenses_net_total,
        "invoice_total": invoice_total,
    }

    html_string = render_to_string("invoicing/invoice.html", context)
    html = HTML(string=html_string, base_url=request.build_absolute_uri())

    with NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        html.write_pdf(
            target=pdf_file.name,
            stylesheets=[
                BASE_DIR.joinpath(os.path.join("static", "css", "invoice_template.css"))
            ],
        )
        pdf_file.seek(0)

    return pdf_file
