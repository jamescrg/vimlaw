from django.urls import path

from apps.trust.views import (
    add,
    client,
    client_index,
    delete,
    edit,
    history,
    history_index,
    toggle_confirmed,
    toggle_entered,
    trust_index,
    trust_list,
)

app_name = "trust"

urlpatterns = [
    path("trust/", trust_index, name="index"),
    path("trust/list/", trust_list, name="trust"),
    path("trust/history/<str:interval>/", history_index, name="history-index"),
    path("trust/history/<str:interval>/detail/", history, name="history"),
    path("trust/client/<int:id>/", client_index, name="client-index"),
    path("trust/client/<int:id>/details/", client, name="client"),
    path("trust/add", add, name="add"),
    path("trust/add/<int:client_id>", add, name="add-with-client"),
    path("trust/<int:id>/edit", edit, name="edit"),
    path("trust/<int:id>/delete", delete, name="delete"),
    path("trust/<int:id>/entered", toggle_entered, name="entered"),
    path("trust/<int:id>/confirmed", toggle_confirmed, name="confirmed"),
]
