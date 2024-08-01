from django.urls import path

from apps.invoicing.views.invoice import (
    AddInvoiceView,
    CancelInvoiceView,
    DeleteInvoiceView,
    InvoiceDetailView,
    InvoicePDFView,
    StatusUpdateView,
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
    path("invoicing/add-invoice/", AddInvoiceView.as_view(), name="add-invoice"),
    path(
        "invoicing/delete-invoice/<int:pk>/",
        DeleteInvoiceView.as_view(),
        name="delete-invoice",
    ),
    path(
        "invoicing/invoice-pdf/<int:pk>/", InvoicePDFView.as_view(), name="invoice-pdf"
    ),
    path(
        "invoicing/status-update/<int:pk>/",
        StatusUpdateView.as_view(),
        name="status-update",
    ),
    path(
        "invoicing/cancel-invoice/<int:pk>/",
        CancelInvoiceView.as_view(),
        name="cancel-invoice",
    ),
]
