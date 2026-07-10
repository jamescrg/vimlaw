from django.urls import path

from apps.invoicing.pay.views import (
    balance_charge,
    balance_invoice_pdf,
    balance_pay_page,
    balance_statement_pdf,
    pay_charge,
    pay_invoice_pdf,
    pay_page,
    processor_webhook,
)

app_name = "pay"

urlpatterns = [
    # Public, tokenized — no login. The signed token carries the invoice uuid.
    path("pay/<str:token>/", pay_page, name="invoice"),
    path("pay/<str:token>/charge/", pay_charge, name="charge"),
    # Passwordless PDF download behind the same token as the pay page.
    path("pay/<str:token>/invoice.pdf", pay_invoice_pdf, name="invoice-pdf"),
    # Catch-up: pay a matter's full open balance (token carries the matter id).
    path("pay/balance/<str:token>/", balance_pay_page, name="balance"),
    path("pay/balance/<str:token>/charge/", balance_charge, name="balance-charge"),
    path(
        "pay/balance/<str:token>/statement.pdf",
        balance_statement_pdf,
        name="balance-statement-pdf",
    ),
    path(
        "pay/balance/<str:token>/invoice/<int:invoice_id>.pdf",
        balance_invoice_pdf,
        name="balance-invoice-pdf",
    ),
    # Processor settlement/return notifications (verified by re-fetch).
    path("webhooks/<str:processor>/", processor_webhook, name="webhook"),
]
