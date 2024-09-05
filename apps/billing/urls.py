from django.urls import path

from apps.billing.invoices.views import (
    invoices_add,
    invoices_delete,
    invoices_detail,
    invoices_edit,
    invoices_edit_status,
    invoices_filter,
    invoices_list,
    invoices_pdf,
)
from apps.billing.payments.views import (
    payments_add,
    payments_delete,
    payments_edit,
    payments_filter,
    payments_list,
)

app_name = "billing"

urlpatterns = [
    path("billing/", invoices_list, name="invoices-list"),
    path(
        "billing/invoices-detail/<int:pk>/preview/",
        invoices_detail,
        name="invoices-detail",
    ),
    path("billing/invoices-add/", invoices_add, name="invoices-add"),
    path("billing/invoices-edit/<int:pk>/", invoices_edit, name="invoices-edit"),
    path("billing/invoices-filter/", invoices_filter, name="invoices-filter"),
    path("billing/invoices-delete/<int:pk>/", invoices_delete, name="invoices-delete"),
    path("billing/invoices-pdf/<int:pk>/", invoices_pdf, name="invoices-pdf"),
    path(
        "billing/invoices-edit-status/<int:pk>/",
        invoices_edit_status,
        name="invoices-edit-status",
    ),
    path("billing/payments/", payments_list, name="payments-list"),
    path("billing/payments-add/", payments_add, name="payments-add"),
    path("billing/payments-delete/<int:pk>/", payments_delete, name="payments-delete"),
    path("billing/payments-edit/<int:pk>/", payments_edit, name="payments-edit"),
    path("billing/payments-filter/", payments_filter, name="payments-filter"),
]
