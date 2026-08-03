import os
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.files.base import ContentFile
from django.core.handlers.wsgi import WSGIRequest
from django.template.loader import render_to_string
from weasyprint import HTML, default_url_fetcher

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.flat_fees.models import FlatFeeEntry
from apps.activity.time.models import TimeEntry
from apps.invoicing.invoices.models import Invoice
from apps.settings.models import Firm
from apps.trust.trust import get_confirmed_client_balance


def _static_file_url_fetcher(url):
    """URL fetcher that resolves static and media files from the filesystem.

    Handles two issues with file:// URL resolution:
    1. Absolute paths (/static/..., /media/...) cause urljoin to ignore the
       base_url, resolving to file:///static/... instead of
       file://<BASE_DIR>/static/...
    2. Cache buster query strings (?v=...) break filesystem lookups.
    """
    parsed = urlparse(url)
    if parsed.scheme == "file":
        clean_path = parsed.path
        # If the file exists as-is (no query string issue), use it directly
        if os.path.isfile(clean_path):
            return default_url_fetcher(f"file://{clean_path}")
        # Extract the relative path after the static prefix
        static_prefix = "/" + settings.STATIC_URL.strip("/") + "/"
        if static_prefix in clean_path:
            relative_path = clean_path.split(static_prefix, 1)[1]
            # Try Django's staticfiles finders (works with DEBUG=True)
            found = finders.find(relative_path)
            if found:
                return default_url_fetcher(f"file://{found}")
            # Fall back to STATIC_ROOT (works with DEBUG=False)
            if settings.STATIC_ROOT:
                static_root_path = os.path.join(settings.STATIC_ROOT, relative_path)
                if os.path.isfile(static_root_path):
                    return default_url_fetcher(f"file://{static_root_path}")
        # Media uploads (the firm logo in the PDF header) live under
        # MEDIA_ROOT, which no finder covers
        media_prefix = "/" + settings.MEDIA_URL.strip("/") + "/"
        if media_prefix in clean_path:
            relative_path = clean_path.split(media_prefix, 1)[1]
            media_path = settings.MEDIA_ROOT / relative_path
            if os.path.isfile(media_path):
                return default_url_fetcher(f"file://{media_path}")
    return default_url_fetcher(url)


def generate_invoice(
    invoice: Invoice, request: WSGIRequest = None, *, base_url: str = ""
) -> NamedTemporaryFile:
    """
    Generate a PDF invoice for the given invoice instance.

    Either request or base_url must be provided for resolving static file paths.
    """

    if invoice.show_comp:
        time_entries = TimeEntry.objects.filter(
            invoice=invoice,
        ).order_by("date")
        expenses = ExpenseEntry.objects.filter(
            invoice=invoice,
        ).order_by("date")
        flat_fee_entries = FlatFeeEntry.objects.filter(
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
        flat_fee_entries = FlatFeeEntry.objects.filter(
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
        "flat_fee_entries": flat_fee_entries,
        "confirmed_balance": confirmed_balance,
        "company": Firm.objects.first(),
    }

    html_string = render_to_string("invoicing/invoices/invoice.html", context)
    if not base_url and request:
        base_url = request.build_absolute_uri("/").rstrip("/")
    url_fetcher = _static_file_url_fetcher if base_url.startswith("file://") else None
    html = HTML(string=html_string, base_url=base_url, url_fetcher=url_fetcher)

    with NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        html.write_pdf(target=pdf_file.name)
        pdf_file.seek(0)

    return pdf_file


def store_invoice_pdf(
    invoice: Invoice, request: WSGIRequest = None, *, base_url: str = ""
) -> None:
    """Generate PDF and store it in the invoice's pdf_file field."""
    pdf_file = generate_invoice(invoice, request, base_url=base_url)

    with open(pdf_file.name, "rb") as f:
        pdf_content = f.read()

    os.unlink(pdf_file.name)

    filename = f"invoice_{invoice.id}.pdf"

    if invoice.pdf_file:
        invoice.pdf_file.delete(save=False)

    invoice.pdf_file.save(filename, ContentFile(pdf_content), save=False)
    Invoice.objects.filter(pk=invoice.pk).update(pdf_file=invoice.pdf_file)
