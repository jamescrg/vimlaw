from django.urls import path

from apps.intakes.views import (
    add,
    add_note,
    delete,
    delete_note,
    detail,
    detail_data,
    edit,
    edit_note,
    index,
    intake_edit_status,
    intake_filter,
    order_by,
    quick_filter_all,
    quick_filter_status,
)

app_name = "intakes"

urlpatterns = [
    path("intakes/", index, name="list"),
    path("intakes/<int:id>", detail, name="detail"),
    path("intakes/<int:id>/data", detail_data, name="detail-data"),
    path("intakes/add", add, name="add"),
    path("intakes/<int:id>/edit", edit, name="edit"),
    path("intakes/<int:id>/delete", delete, name="delete"),
    path("intakes/<int:id>/add-note", add_note, name="add_note"),
    path("intakes/<int:id>/edit-note", edit_note, name="edit_note"),
    path("intakes/<int:id>/delete-note", delete_note, name="delete_note"),
    path("intakes/filter-intakes", intake_filter, name="filter-intakes"),
    path(
        "intakes/quick-filter-status/<str:status>",
        quick_filter_status,
        name="quick-filter-status",
    ),
    path("intakes/quick-filter-all", quick_filter_all, name="quick-filter-all"),
    path("intakes/order-by/<str:order>", order_by, name="order-by"),
    path(
        "intakes/edit-status/<int:pk>/<str:status>",
        intake_edit_status,
        name="edit-status",
    ),
]
