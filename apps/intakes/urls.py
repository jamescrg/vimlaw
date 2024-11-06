from django.urls import path

from apps.intakes.views import (
    add,
    add_note,
    delete,
    delete_note,
    detail,
    detail_index,
    edit,
    edit_note,
    intake_edit_status,
    intake_filter,
    intakes_index,
    intakes_list,
    order_by,
    quick_filter_all,
    quick_filter_status,
)

app_name = "intakes"

urlpatterns = [
    path("intakes/", intakes_index, name="index"),
    path("intakes/list/", intakes_list, name="list"),
    path("intakes/<int:id>/", detail_index, name="detail-index"),
    path("intakes/<int:id>/detail/", detail, name="detail"),
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
