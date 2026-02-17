from tempfile import NamedTemporaryFile

from django.core.handlers.wsgi import WSGIRequest
from django.template.loader import render_to_string
from weasyprint import HTML

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.time.models import TimeEntry
from apps.invoicing.invoices.models import Invoice
from apps.settings.models import Company
from apps.trust.trust import get_confirmed_client_balance


def generate_invoice(invoice: Invoice, request: WSGIRequest) -> NamedTemporaryFile:
    """
    Generate a PDF invoice for the given invoice instance
    """

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

    # Get confirmed trust balance for the client
    confirmed_balance = 0
    if invoice.matter.client:
        confirmed_balance = get_confirmed_client_balance(invoice.matter.client.id)

    context = {
        "invoice": invoice,
        "time_entries": time_entries,
        "expenses": expenses,
        "confirmed_balance": confirmed_balance,
        "company": Company.objects.first(),
    }

    html_string = render_to_string("invoicing/invoices/invoice.html", context)
    base_url = request.build_absolute_uri("/").rstrip("/")
    html = HTML(string=html_string, base_url=base_url)

    with NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        html.write_pdf(target=pdf_file.name)
        pdf_file.seek(0)

    return pdf_file
