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

urlpatterns = [
    path("intakes/", index, name="intakes-list"),
    path("intakes/list/data", list_data, name="intakes-list-data"),
    path("intakes/<int:id>", detail, name="intakes-detail"),
    path("intakes/<int:id>/data", detail_data, name="intakes-detail-data"),
    path("intakes/add", add, name="intakes-add"),
    path("intakes/<int:id>/edit", edit, name="intakes-edit"),
    path("intakes/<int:id>/delete", delete, name="intakes-delete"),
    path("intakes/filter", filter, name="intakes-filter"),
    path("intakes/filter/update", filter_update, name="intakes-filter-update"),
    path(
        "intakes/filter/<str:quick_filter>",
        filter_quick,
        name="intakes-filter-quick",
    ),
    path("intakes/sort/<str:order>", order, name="intakes-sort-by"),
    path("intakes/<int:id>/add-note", add_note, name="intakes-add_note"),
    path("intakes/<int:id>/edit-note", edit_note, name="intakes-edit_note"),
    path("intakes/<int:id>/delete-note", delete_note, name="intakes-delete_note"),
]
