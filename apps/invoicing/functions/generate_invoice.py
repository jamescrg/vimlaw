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
            matter=invoice.matter,
            date__range=[invoice.date_from, invoice.date_to],
            invoice=invoice,
        ).order_by("date")
    else:
        entries = TimeEntry.objects.filter(
            matter=invoice.matter,
            date__range=[invoice.date_from, invoice.date_to],
            invoice=invoice,
            comp=invoice.show_comp,
        ).order_by("date")

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
        ).order_by("date")
    else:
        expenses = ExpenseEntry.objects.filter(
            matter=invoice.matter,
            date__range=[invoice.date_from, invoice.date_to],
            invoice=invoice,
            comp=invoice.show_comp,
        ).order_by("date")
    expenses_total = expenses.aggregate(total_amount=Sum("amount"))["total_amount"] or 0

    pre_discount_total = entries_total + expenses_total
    combined_total = pre_discount_total - invoice.discount

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
