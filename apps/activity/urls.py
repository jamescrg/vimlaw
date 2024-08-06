from django.urls import path

from apps.activity.views import (
    add,
    add_expense,
    delete,
    delete_expense,
    edit,
    edit_expense,
    export,
    filter,
    filter_matter,
    filter_quick,
    filter_update,
    index,
    set_tab,
    toggle_entered,
    toggle_entered_expense,
)

app_name = "activity"

urlpatterns = [
    path("activity/", index, name="list"),
    path("activity/add", add, name="add"),
    path("activity/add_expense", add_expense, name="add-expense"),
    path("activity/add/<int:id>", add, name="add"),
    path(
        "activity/add_expense/<int:id>",
        add_expense,
        name="add-expense",
    ),
    path("activity/<int:id>/edit", edit, name="edit"),
    path(
        "activity/<int:id>/edit_expense",
        edit_expense,
        name="edit-expense",
    ),
    path("activity/<int:id>/delete", delete, name="delete"),
    path(
        "activity/<int:id>/delete_expense",
        delete_expense,
        name="delete-expense",
    ),
    path(
        "activity/<int:id>/toggle-entered",
        toggle_entered,
        name="toggle-entered",
    ),
    path(
        "activity/<int:id>/toggle-entered-expense",
        toggle_entered_expense,
        name="toggle-entered-expense",
    ),
    path("activity/filter", filter, name="filter"),
    path("activity/filter/update", filter_update, name="filter-update"),
    path(
        "activity/filter/<str:quick_filter>",
        filter_quick,
        name="filter-quick",
    ),
    path(
        "activity/filter/matter/<int:id>",
        filter_matter,
        name="filter-matter",
    ),
    path("activity/export", export, name="export"),
    path(
        "activity/set-tab/<str:tab>",
        set_tab,
        name="set-tab",
    ),
]
