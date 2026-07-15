from django.urls import path

from apps.trust.views import (
    add,
    client,
    client_index,
    delete,
    edit,
    history,
    history_csv,
    history_index,
    order_by,
    toggle_confirmed,
    toggle_entered,
    trust_index,
    trust_list,
)

app_name = "trust"

urlpatterns = [
    path("invoicing/trust/", trust_index, name="index"),
    path("invoicing/trust/list/", trust_list, name="trust"),
    path("invoicing/trust/order-by/<str:order>/", order_by, name="order-by"),
    path("invoicing/trust/history/export.csv", history_csv, name="history-csv"),
    path(
        "invoicing/trust/history/<str:interval>/", history_index, name="history-index"
    ),
    path("invoicing/trust/history/<str:interval>/detail/", history, name="history"),
    path("invoicing/trust/client/<int:id>/", client_index, name="client-index"),
    path("invoicing/trust/client/<int:id>/details/", client, name="client"),
    path("invoicing/trust/add", add, name="add"),
    path("invoicing/trust/add/<int:client_id>", add, name="add-with-client"),
    path("invoicing/trust/<int:id>/edit", edit, name="edit"),
    path("invoicing/trust/<int:id>/delete", delete, name="delete"),
    path("invoicing/trust/<int:id>/entered", toggle_entered, name="entered"),
    path("invoicing/trust/<int:id>/confirmed", toggle_confirmed, name="confirmed"),
]
