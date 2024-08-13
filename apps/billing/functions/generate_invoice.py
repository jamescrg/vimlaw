import os
from tempfile import NamedTemporaryFile

from django.core.handlers.wsgi import WSGIRequest
from django.template.loader import render_to_string
from weasyprint import HTML

from apps.billing.functions.calculate_inv_amount import calculate_inv_amount
from apps.billing.models_invoice import Invoice
from config.settings import BASE_DIR


def generate_invoice(invoice: Invoice, request: WSGIRequest) -> NamedTemporaryFile:
    """
    Generate a PDF invoice for the given invoice instance
    """
    calc = calculate_inv_amount(invoice)

    context = {
        "invoice": invoice,
        "entries": calc["entries"],
        "expenses": calc["expenses"],
        "entries_gross_total": calc["entries_gross_total"],
        "entries_comp_total": calc["entries_comp_total"],
        "entries_net_total": calc["entries_net_total"],
        "expenses_gross_total": calc["expenses_gross_total"],
        "expenses_comp_total": calc["expenses_comp_total"],
        "expenses_net_total": calc["expenses_net_total"],
        "invoice_total": calc["invoice_total"],
    }

    html_string = render_to_string("billing/invoice.html", context)
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
