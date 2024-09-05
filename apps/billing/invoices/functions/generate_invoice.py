import os
from tempfile import NamedTemporaryFile

from django.core.handlers.wsgi import WSGIRequest
from django.template.loader import render_to_string
from weasyprint import HTML

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.billing.invoices.models import Invoice
from config.settings import BASE_DIR


def generate_invoice(invoice: Invoice, request: WSGIRequest) -> NamedTemporaryFile:
    """
    Generate a PDF invoice for the given invoice instance
    """

    # get list of time and expense enties for inclusion in invoice
    if invoice.show_comp:
        time_entries = TimeEntry.objects.filter(
            invoice=invoice,
        ).order_by("date")
        expenses = ExpenseEntry.objects.filter(
            invoice=invoice,
        ).order_by("date")
    else:
        time_entries = TimeEntry.objects.filter(
            invoice=invoice,
            comp=invoice.show_comp,
        ).order_by("date")
        expenses = ExpenseEntry.objects.filter(
            invoice=invoice,
            comp=invoice.show_comp,
        ).order_by("date")

    # pass invoice and associated time and expense entries to template
    context = {
        "invoice": invoice,
        "time_entries": time_entries,
        "expenses": expenses,
    }

    html_string = render_to_string("billing/invoices/invoice.html", context)
    html = HTML(string=html_string, base_url=request.build_absolute_uri())

    with NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        html.write_pdf(
            target=pdf_file.name,
            stylesheets=[
                BASE_DIR.joinpath(
                    os.path.join("static", "css", "apps", "billing", "invoice.css")
                )
            ],
        )
        pdf_file.seek(0)

    return pdf_file
