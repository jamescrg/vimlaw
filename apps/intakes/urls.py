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
    filter,
    filter_quick,
    filter_update,
    index,
    list_data,
    order,
)

app_name = "intakes"

urlpatterns = [
    path("intakes/", index, name="list"),
    path("intakes/list/data", list_data, name="list-data"),
    path("intakes/<int:id>", detail, name="detail"),
    path("intakes/<int:id>/data", detail_data, name="detail-data"),
    path("intakes/add", add, name="add"),
    path("intakes/<int:id>/edit", edit, name="edit"),
    path("intakes/<int:id>/delete", delete, name="delete"),
    path("intakes/filter", filter, name="filter"),
    path("intakes/filter/update", filter_update, name="filter-update"),
    path(
        "intakes/filter/<str:quick_filter>",
        filter_quick,
        name="filter-quick",
    ),
    path("intakes/sort/<str:order>", order, name="sort-by"),
    path("intakes/<int:id>/add-note", add_note, name="add_note"),
    path("intakes/<int:id>/edit-note", edit_note, name="edit_note"),
    path("intakes/<int:id>/delete-note", delete_note, name="delete_note"),
]
