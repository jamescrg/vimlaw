from django.urls import path

from apps.billing.invoice.views import (
    add_invoice,
    cancel_invoice,
    delete_invoice,
    edit_invoice,
    invoice_detail,
    invoice_filter,
    invoice_pdf,
    status_update,
)
from apps.billing.payment.views import (
    add_payment,
    delete_payment,
    edit_payment,
    payment_filter,
)
from apps.billing.views import billing_index, set_tab

app_name = "billing"

urlpatterns = [
    path("billing/", billing_index, name="billing"),
    path("billing/set-tab/<str:tab>/", set_tab, name="set-tab"),
    path(
        "billing/invoice-detail/<int:pk>/preview/",
        invoice_detail,
        name="invoice-detail",
    ),
    path("billing/add-invoice/", add_invoice, name="add-invoice"),
    path(
        "billing/edit-invoice/<int:pk>/",
        edit_invoice,
        name="edit-invoice",
    ),
    path(
        "billing/delete-invoice/<int:pk>/",
        delete_invoice,
        name="delete-invoice",
    ),
    path("billing/invoice-pdf/<int:pk>/", invoice_pdf, name="invoice-pdf"),
    path(
        "billing/status-update/<int:pk>/",
        status_update,
        name="status-update",
    ),
    path(
        "billing/cancel-invoice/<int:pk>/",
        cancel_invoice,
        name="cancel-invoice",
    ),
    path("billing/add-payment/", add_payment, name="add-payment"),
    path(
        "billing/delete-payment/<int:pk>/",
        delete_payment,
        name="delete-payment",
    ),
    path(
        "billing/edit-payment/<int:pk>/",
        edit_payment,
        name="edit-payment",
    ),
    path(
        "billing/payment-filter/",
        payment_filter,
        name="filter-payments",
    ),
    path(
        "billing/invoice-filter/",
        invoice_filter,
        name="filter-invoices",
    ),
]
