from django.urls import path

from apps.invoicing.views.invoice import NewInvoiceView, index

app_name = "invoicing"

urlpatterns = [
    path("invoicing/", index, name="invoicing"),
    path("invoicing/new-invoice/", NewInvoiceView.as_view(), name="new-invoice"),
]
