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

urlpatterns = [
    path("trust/", index, name="trust"),
    path("trust/history/", history, name="trust-history"),
    path("trust/history/<str:interval>/", history, name="trust-history-interval"),
    path("trust/client/<int:id>", client, name="trust-client"),
    path("trust/<int:contact_id>/add", add, name="trust-add"),
    path("trust/<int:id>/edit", edit, name="trust-edit"),
    path("trust/<int:id>/delete", delete, name="trust-delete"),
    path("trust/<int:id>/entered", toggle_entered, name="trust-entered"),
    path("trust/<int:id>/confirmed", toggle_confirmed, name="trust-confirmed"),
]
