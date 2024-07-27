from django.urls import path

from apps.invoicing.views.invoice import (
    DeleteInvoiceView,
    InvoiceDetailView,
    InvoicePDFView,
    NewInvoiceView,
    index,
)

app_name = "invoicing"

urlpatterns = [
    path("invoicing/", index, name="invoicing"),
    path(
        "invoicing/invoice-detail/<int:pk>/preview/",
        InvoiceDetailView.as_view(),
        name="invoice-detail",
    ),
    path("invoicing/new-invoice/", NewInvoiceView.as_view(), name="new-invoice"),
    path(
        "invoicing/delete-invoice/<int:pk>/",
        DeleteInvoiceView.as_view(),
        name="delete-invoice",
    ),
    path(
        "invoicing/invoice-pdf/<int:pk>/", InvoicePDFView.as_view(), name="invoice-pdf"
    ),
]
