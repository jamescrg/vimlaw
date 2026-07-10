"""Build public payment links for an invoice."""

from django.conf import settings
from django.urls import reverse

from utils.signing import make_payment_token, make_request_token


def _absolute(path, request):
    if request is not None:
        return request.build_absolute_uri(path)
    base = (getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/")
    return f"{base}{path}" if base else path


def payment_path(invoice) -> str:
    """Root-relative payment URL, e.g. /pay/<signed-token>/."""
    return reverse("pay:invoice", kwargs={"token": make_payment_token(invoice)})


def payment_url(invoice, request=None) -> str:
    """Absolute payment URL for emails / off-request contexts.

    Uses the request host when available, else settings.PUBLIC_BASE_URL.
    """
    return _absolute(payment_path(invoice), request)


def request_pay_path(payment_request) -> str:
    """Root-relative catch-up (full-balance) payment URL for a PaymentRequest."""
    return reverse("pay:balance", kwargs={"token": make_request_token(payment_request)})


def request_pay_url(payment_request, request=None) -> str:
    """Absolute PaymentRequest payment URL (see payment_url)."""
    return _absolute(request_pay_path(payment_request), request)


def request_statement_pdf_url(payment_request, request=None) -> str:
    """Absolute tokenized matter-statement download URL (for request emails)."""
    path = reverse(
        "pay:balance-statement-pdf",
        kwargs={"token": make_request_token(payment_request)},
    )
    return _absolute(path, request)


def request_invoice_pdf_url(payment_request, invoice_id, request=None) -> str:
    """Absolute tokenized invoice-PDF download URL (for request emails)."""
    path = reverse(
        "pay:balance-invoice-pdf",
        kwargs={
            "token": make_request_token(payment_request),
            "invoice_id": invoice_id,
        },
    )
    return _absolute(path, request)
