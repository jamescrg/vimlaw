from django.urls import path

from apps.billing.views.invoice import (
    AddInvoiceView,
    BillingIndex,
    CancelInvoiceView,
    DeleteInvoiceView,
    EditInvoiceView,
    InvoiceDetailView,
    InvoicePDFView,
    StatusUpdateView,
    set_tab,
)
from apps.billing.views.payment import (
    AddPaymentView,
    EditPaymentView,
    PaymentFilterView,
    delete_payment,
)

app_name = "billing"

urlpatterns = [
    path("billing/", BillingIndex.as_view(), name="billing"),
    path("billing/set-tab/<str:tab>/", set_tab, name="set-tab"),
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
    path("billing/add-payment/", AddPaymentView.as_view(), name="add-payment"),
    path(
        "billing/delete-payment/<int:pk>/",
        delete_payment,
        name="delete-payment",
    ),
    path(
        "billing/edit-payment/<int:pk>/",
        EditPaymentView.as_view(),
        name="edit-payment",
    ),
    path(
        "billing/payment-filter/",
        PaymentFilterView.as_view(),
        name="filter-payments",
    ),
]
