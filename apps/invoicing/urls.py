from django.urls import path

from apps.invoicing.collection.views import collection_index, collection_list
from apps.invoicing.credits.views import (
    credits_add,
    credits_apply,
    credits_delete,
    credits_delete_application,
    credits_edit,
    credits_filter,
    credits_filter_application,
    credits_index,
    credits_list,
    order_by_credits,
)
from apps.invoicing.invoices.views import (
    invoice_details_index,
    invoice_expense_entries,
    invoice_expense_entries_index,
    invoice_expense_order_by,
    invoice_flat_fee_entries,
    invoice_flat_fee_entries_index,
    invoice_history_index,
    invoice_ledes_98b,
    invoice_tab_content,
    invoice_time_bulk_update_comp,
    invoice_time_clear_selection,
    invoice_time_entries,
    invoice_time_entries_index,
    invoice_time_order_by,
    invoice_time_select_all,
    invoice_time_toggle_select,
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
    invoices_send,
    invoices_void,
    invoices_void_confirm,
    order_by_invoices,
    pdf_preview,
    pdf_preview_index,
    quick_invoice_payment,
)
from apps.invoicing.payments.views import (
    order_by_payments,
    payments_add,
    payments_apply,
    payments_delete,
    payments_delete_application,
    payments_edit,
    payments_filter,
    payments_filter_application,
    payments_index,
    payments_list,
)
from apps.invoicing.requests.views import (
    requests_cancel,
    requests_filter,
    requests_filter_status,
    requests_index,
    requests_list,
    requests_matter_fields,
    requests_new,
    requests_resend,
)
from apps.invoicing.unbilled.views import (
    unbilled_bulk_create_invoices,
    unbilled_clear_selection,
    unbilled_filter,
    unbilled_filter_period,
    unbilled_index,
    unbilled_list,
    unbilled_select_all,
    unbilled_sort,
    unbilled_toggle_select,
)

app_name = "invoicing"

urlpatterns = [
    # Invoices (default)
    path("invoicing/", invoices_index, name="invoices-index"),
    # Unbilled
    path("invoicing/unbilled/", unbilled_index, name="unbilled-index"),
    path("invoicing/unbilled/list/", unbilled_list, name="unbilled-list"),
    path("invoicing/unbilled/sort/<str:order>/", unbilled_sort, name="unbilled-sort"),
    path("invoicing/unbilled/filter/", unbilled_filter, name="unbilled-filter"),
    path(
        "invoicing/unbilled/filter-period/<str:period>/",
        unbilled_filter_period,
        name="unbilled-filter-period",
    ),
    path(
        "invoicing/unbilled/toggle-select/<int:matter_id>/",
        unbilled_toggle_select,
        name="unbilled-toggle-select",
    ),
    path(
        "invoicing/unbilled/select-all/",
        unbilled_select_all,
        name="unbilled-select-all",
    ),
    path(
        "invoicing/unbilled/clear-selection/",
        unbilled_clear_selection,
        name="unbilled-clear-selection",
    ),
    path(
        "invoicing/unbilled/bulk-create-invoices/",
        unbilled_bulk_create_invoices,
        name="unbilled-bulk-create-invoices",
    ),
    # Collection
    path("invoicing/collection/", collection_index, name="collection-index"),
    path("invoicing/collection/list/", collection_list, name="collection-list"),
    # Invoices
    path("invoicing/invoices/list/", invoices_list, name="invoices-list"),
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
    path(
        "invoicing/invoices-detail/<int:pk>/tab/<str:tab>/",
        invoice_tab_content,
        name="invoice-tab-content",
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
    path("invoicing/invoices-void/<int:pk>/", invoices_void, name="invoices-void"),
    path(
        "invoicing/invoices-void-confirm/<int:pk>/",
        invoices_void_confirm,
        name="invoices-void-confirm",
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
        "invoicing/invoices/<int:pk>/send/",
        invoices_send,
        name="invoices-send",
    ),
    path(
        "invoicing/invoices-detail/<int:pk>/details-index/",
        invoice_details_index,
        name="invoice-details-index",
    ),
    path(
        "invoicing/invoices-detail/<int:pk>/history-index/",
        invoice_history_index,
        name="invoice-history-index",
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
        "invoicing/invoices-detail/<int:pk>/time-entries/toggle-select/<int:entry_id>/",
        invoice_time_toggle_select,
        name="invoice-time-toggle-select",
    ),
    path(
        "invoicing/invoices-detail/<int:pk>/time-entries/select-all/",
        invoice_time_select_all,
        name="invoice-time-select-all",
    ),
    path(
        "invoicing/invoices-detail/<int:pk>/time-entries/clear-selection/",
        invoice_time_clear_selection,
        name="invoice-time-clear-selection",
    ),
    path(
        "invoicing/invoices-detail/<int:pk>/time-entries/bulk-update-comp/",
        invoice_time_bulk_update_comp,
        name="invoice-time-bulk-update-comp",
    ),
    path(
        "invoicing/invoices-detail/<int:pk>/time-entries/order-by/<str:order>/",
        invoice_time_order_by,
        name="invoice-time-order-by",
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
        "invoicing/invoices-detail/<int:pk>/expense-entries/order-by/<str:order>/",
        invoice_expense_order_by,
        name="invoice-expense-order-by",
    ),
    path(
        "invoicing/invoices-detail/<int:pk>/flat-fee-entries-index/",
        invoice_flat_fee_entries_index,
        name="invoice-flat-fee-entries-index",
    ),
    path(
        "invoicing/invoices-detail/<int:pk>/flat-fee-entries/",
        invoice_flat_fee_entries,
        name="invoice-flat-fee-entries",
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
    path(
        "invoicing/payments-apply/<int:pk>/",
        payments_apply,
        name="payments-apply",
    ),
    path(
        "invoicing/payments-application-delete/<int:pk>/",
        payments_delete_application,
        name="payments-application-delete",
    ),
    path("invoicing/payments-filter/", payments_filter, name="payments-filter"),
    path(
        "invoicing/payments/filter/application/<str:applied>",
        payments_filter_application,
        name="payments-filter-application",
    ),
    path(
        "invoicing/payments-filter/order-by/<str:order>",
        order_by_payments,
        name="payments-order-by",
    ),
    # Requests (catch-up payment requests)
    path("invoicing/requests/", requests_index, name="requests-index"),
    path("invoicing/requests/list/", requests_list, name="requests-list"),
    path("invoicing/requests-new/", requests_new, name="requests-new"),
    path(
        "invoicing/requests-matter-fields/",
        requests_matter_fields,
        name="requests-matter-fields",
    ),
    path(
        "invoicing/requests-cancel/<int:pk>/",
        requests_cancel,
        name="requests-cancel",
    ),
    path(
        "invoicing/requests-resend/<int:pk>/",
        requests_resend,
        name="requests-resend",
    ),
    path("invoicing/requests-filter/", requests_filter, name="requests-filter"),
    path(
        "invoicing/requests/filter/status/<str:status>",
        requests_filter_status,
        name="requests-filter-status",
    ),
    # Credits
    path("invoicing/credits/", credits_index, name="credits-index"),
    path("invoicing/credits/list/", credits_list, name="credits-list"),
    path("invoicing/credits-add/", credits_add, name="credits-add"),
    path("invoicing/credits-edit/<int:pk>/", credits_edit, name="credits-edit"),
    path(
        "invoicing/credits-apply/<int:pk>/",
        credits_apply,
        name="credits-apply",
    ),
    path(
        "invoicing/credits-application-delete/<int:pk>/",
        credits_delete_application,
        name="credits-application-delete",
    ),
    path("invoicing/credits-delete/<int:pk>/", credits_delete, name="credits-delete"),
    path(
        "invoicing/order-by-credits/<str:order>",
        order_by_credits,
        name="order-by-credits",
    ),
    path("invoicing/credits-filter/", credits_filter, name="credits-filter"),
    path(
        "invoicing/credits/filter/application/<str:applied>",
        credits_filter_application,
        name="credits-filter-application",
    ),
]
