from django.urls import path

from apps.invoicing.collection.views import collection_index, collection_list
from apps.invoicing.credits.views import (
    credits_add,
    credits_delete,
    credits_edit,
    credits_filter,
    credits_index,
    credits_list,
    order_by_credits,
)
from apps.invoicing.invoices.views import (
    invoice_details_index,
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
    invoices_pdf_download,
    order_by_invoices,
    pdf_preview,
    pdf_preview_index,
    quick_invoice_payment,
)
from apps.invoicing.payments.views import (
    order_by_payments,
    payments_add,
    payments_delete,
    payments_edit,
    payments_filter,
    payments_index,
    payments_list,
)
from apps.invoicing.unbilled.views import unbilled_index, unbilled_list, unbilled_sort

app_name = "invoicing"

urlpatterns = [
    # Unbilled
    path("invoicing/unbilled/", unbilled_index, name="unbilled-index"),
    path("invoicing/unbilled/list/", unbilled_list, name="unbilled-list"),
    path("invoicing/unbilled/sort/<str:order>/", unbilled_sort, name="unbilled-sort"),
    # Collection
    path("invoicing/collection/", collection_index, name="collection-index"),
    path("invoicing/collection/list/", collection_list, name="collection-list"),
    # Invoices
    path("invoicing/", invoices_index, name="invoices-index"),
    path("invoicing/list/", invoices_list, name="invoices-list"),
    path(
        "invoicing/invoices-detail/<int:pk>/",
        invoices_detail_index,
        name="invoices-detail-index",
    ),
    path(
        "invoicing/invoices-detail/<int:pk>/detail/",
        invoices_detail,
        name="invoices-detail",
    ),
    path("invoicing/invoices-add/", invoices_add, name="invoices-add"),
    path("invoicing/invoices-edit/<int:pk>/", invoices_edit, name="invoices-edit"),
    path("invoicing/invoices-filter/", invoices_filter, name="invoices-filter"),
    path(
        "invoicing/invoices-filter-status/<str:status>",
        invoices_filter_status,
        name="invoices-filter-status",
    ),
    path(
        "invoicing/invoices-filter/order-by/<str:order>",
        order_by_invoices,
        name="invoices-order-by",
    ),
    path(
        "invoicing/invoices-delete/<int:pk>/", invoices_delete, name="invoices-delete"
    ),
    path("invoicing/invoices-pdf/<int:pk>/", invoices_pdf, name="invoices-pdf"),
    path(
        "invoicing/invoices-pdf-download/<int:pk>/",
        invoices_pdf_download,
        name="invoices-pdf-download",
    ),
    path("invoicing/invoice-ledes/<int:pk>/", invoice_ledes_98b, name="invoice-ledes"),
    path(
        "invoicing/invoices-edit-status/<int:pk>/<str:status>/<str:view>/",
        invoices_edit_status,
        name="invoices-edit-status",
    ),
    path(
        "invoicing/invoices-detail/<int:pk>/details-index/",
        invoice_details_index,
        name="invoice-details-index",
    ),
    path(
        "invoicing/invoices-detail/<int:pk>/pdf-preview-index/",
        pdf_preview_index,
        name="invoice-pdf-preview-index",
    ),
    path(
        "invoicing/invoices-detail/<int:pk>/pdf-preview/",
        pdf_preview,
        name="invoice-pdf-preview",
    ),
    path(
        "invoicing/invoices-detail/<int:pk>/time-entries-index/",
        invoice_time_entries_index,
        name="invoice-time-entries-index",
    ),
    path(
        "invoicing/invoices-detail/<int:pk>/time-entries/",
        invoice_time_entries,
        name="invoice-time-entries",
    ),
    path(
        "invoicing/invoices-detail/<int:pk>/expense-entries-index/",
        invoice_expense_entries_index,
        name="invoice-expense-entries-index",
    ),
    path(
        "invoicing/invoices-detail/<int:pk>/expense-entries/",
        invoice_expense_entries,
        name="invoice-expense-entries",
    ),
    path(
        "invoicing/invoice/quick-payment/<int:pk>/<str:payment_type>/",
        quick_invoice_payment,
        name="quick-invoice-payment",
    ),
    # Payments
    path("invoicing/payments/", payments_index, name="payments-index"),
    path("invoicing/payments/list/", payments_list, name="payments-list"),
    path("invoicing/payments-add/", payments_add, name="payments-add"),
    path(
        "invoicing/payments-delete/<int:pk>/", payments_delete, name="payments-delete"
    ),
    path("invoicing/payments-edit/<int:pk>/", payments_edit, name="payments-edit"),
    path("invoicing/payments-filter/", payments_filter, name="payments-filter"),
    path(
        "invoicing/payments-filter/order-by/<str:order>",
        order_by_payments,
        name="payments-order-by",
    ),
    # Credits
    path("invoicing/credits/", credits_index, name="credits-index"),
    path("invoicing/credits/list/", credits_list, name="credits-list"),
    path("invoicing/credits-add/", credits_add, name="credits-add"),
    path("invoicing/credits-edit/<int:pk>/", credits_edit, name="credits-edit"),
    path("invoicing/credits-delete/<int:pk>/", credits_delete, name="credits-delete"),
    path(
        "invoicing/order-by-credits/<str:order>",
        order_by_credits,
        name="order-by-credits",
    ),
    path("invoicing/credits-filter/", credits_filter, name="credits-filter"),
]
