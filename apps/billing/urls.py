from django.urls import path

from apps.billing.views.invoice import (
    AddInvoiceView,
    CancelInvoiceView,
    DeleteInvoiceView,
    EditInvoiceView,
    InvoiceDetailView,
    InvoicePDFView,
    StatusUpdateView,
    index,
)

app_name = "billing"

urlpatterns = [
    path("billing/", index, name="billing"),
    path(
        "billing/invoice-detail/<int:pk>/preview/",
        InvoiceDetailView.as_view(),
        name="invoice-detail",
    ),
    path("billing/add-invoice/", AddInvoiceView.as_view(), name="add-invoice"),
    path(
        "billing/edit-invoice/<int:pk>/",
        EditInvoiceView.as_view(),
        name="edit-invoice",
    ),
    path(
        "billing/delete-invoice/<int:pk>/",
        DeleteInvoiceView.as_view(),
        name="delete-invoice",
    ),
    path("billing/invoice-pdf/<int:pk>/", InvoicePDFView.as_view(), name="invoice-pdf"),
    path(
        "billing/status-update/<int:pk>/",
        StatusUpdateView.as_view(),
        name="status-update",
    ),
    path(
        "billing/cancel-invoice/<int:pk>/",
        CancelInvoiceView.as_view(),
        name="cancel-invoice",
    ),
]
