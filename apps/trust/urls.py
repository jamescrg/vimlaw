from django.urls import path

from apps.trust.views import (
    add,
    client,
    delete,
    edit,
    history,
    index,
    toggle_confirmed,
    toggle_entered,
)

app_name = "trust"

urlpatterns = [
    path("trust/", index, name="trust"),
    path("trust/history/", history, name="history"),
    path("trust/history/<str:interval>/", history, name="history-interval"),
    path("trust/client/<int:id>", client, name="client"),
    path("trust/add", add, name="add"),
    path("trust/add/<int:client_id>", add, name="add-with-client"),
    path("trust/<int:id>/edit", edit, name="edit"),
    path("trust/<int:id>/delete", delete, name="delete"),
    path("trust/<int:id>/entered", toggle_entered, name="entered"),
    path("trust/<int:id>/confirmed", toggle_confirmed, name="confirmed"),
]
