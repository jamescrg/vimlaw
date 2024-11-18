from django.urls import path

from apps.billing.collection.views import collection_index, collection_list
from apps.billing.invoices.views import (
    invoice_expense_entries,
    invoice_expense_entries_index,
    invoice_ledes_98b,
    invoice_time_entries,
    invoice_time_entries_index,
    invoices_add,
    invoices_delete,
    invoices_detail,
    invoices_detail_index,
    invoices_edit,
    invoices_edit_status,
    invoices_filter,
    invoices_filter_status,
    invoices_index,
    invoices_list,
    invoices_pdf,
    order_by_invoices,
    pdf_preview,
    pdf_preview_index,
)
from apps.billing.payments.views import (
    order_by_payments,
    payments_add,
    payments_delete,
    payments_edit,
    payments_filter,
    payments_index,
    payments_list,
)

app_name = "billing"

urlpatterns = [
    # Collection
    path("billing/collection/", collection_index, name="collection-index"),
    path("billing/collection/list/", collection_list, name="collection-list"),
    # Invoices
    path("billing/", invoices_index, name="invoices-index"),
    path("billing/list/", invoices_list, name="invoices-list"),
    path(
        "billing/invoices-detail-index/<int:pk>/",
        invoices_detail_index,
        name="invoices-detail-index",
    ),
    path(
        "billing/invoices-detail/<int:pk>/",
        invoices_detail,
        name="invoices-detail",
    ),
    path("billing/invoices-add/", invoices_add, name="invoices-add"),
    path("billing/invoices-edit/<int:pk>/", invoices_edit, name="invoices-edit"),
    path("billing/invoices-filter/", invoices_filter, name="invoices-filter"),
    path(
        "billing/invoices-filter-status/<str:status>",
        invoices_filter_status,
        name="invoices-filter-status",
    ),
    path(
        "billing/invoices-filter/order-by/<str:order>",
        order_by_invoices,
        name="invoices-order-by",
    ),
    path("billing/invoices-delete/<int:pk>/", invoices_delete, name="invoices-delete"),
    path("billing/invoices-pdf/<int:pk>/", invoices_pdf, name="invoices-pdf"),
    path("billing/invoice-ledes/<int:pk>/", invoice_ledes_98b, name="invoice-ledes"),
    path(
        "billing/invoices-edit-status/<int:pk>/<str:status>/",
        invoices_edit_status,
        name="invoices-edit-status",
    ),
    path(
        "billing/invoices-detail/<int:pk>/pdf-preview-index/",
        pdf_preview_index,
        name="invoice-pdf-preview-index",
    ),
    path(
        "billing/invoices-detail/<int:pk>/pdf-preview/",
        pdf_preview,
        name="invoice-pdf-preview",
    ),
    path(
        "billing/invoices-detail/<int:pk>/time-entries-index/",
        invoice_time_entries_index,
        name="invoice-time-entries-index",
    ),
    path(
        "billing/invoices-detail/<int:pk>/time-entries/",
        invoice_time_entries,
        name="invoice-time-entries",
    ),
    path(
        "billing/invoices-detail/<int:pk>/expense-entries-index/",
        invoice_expense_entries_index,
        name="invoice-expense-entries-index",
    ),
    path(
        "billing/invoices-detail/<int:pk>/expense-entries/",
        invoice_expense_entries,
        name="invoice-expense-entries",
    ),
    # Payments
    path("billing/payments/", payments_index, name="payments-index"),
    path("billing/payments/list/", payments_list, name="payments-list"),
    path("billing/payments-add/", payments_add, name="payments-add"),
    path("billing/payments-delete/<int:pk>/", payments_delete, name="payments-delete"),
    path("billing/payments-edit/<int:pk>/", payments_edit, name="payments-edit"),
    path("billing/payments-filter/", payments_filter, name="payments-filter"),
    path(
        "billing/payments-filter/order-by/<str:order>",
        order_by_payments,
        name="payments-order-by",
    ),
]
