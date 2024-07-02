from django.urls import path

from apps.activity.views import (
    index,
    add,
    add_expense,
    edit,
    edit_expense,
    delete_expense,
    delete,
    toggle_entered_expense,
    toggle_entered,
    filter,
    filter_update,
    filter_quick,
    filter_matter,
    export,
)

urlpatterns = [
    path("activity/", index, name="activity-list"),
    path("activity/add", add, name="activity-add"),
    path("activity/add_expense", add_expense, name="activity-add-expense"),
    path("activity/add/<int:id>", add, name="activity-add"),
    path(
        "activity/add_expense/<int:id>",
        add_expense,
        name="activity-add-expense",
    ),
    path("activity/<int:id>/edit", edit, name="activity-edit"),
    path(
        "activity/<int:id>/edit_expense",
        edit_expense,
        name="activity-edit-expense",
    ),
    path("activity/<int:id>/delete", delete, name="activity-delete"),
    path(
        "activity/<int:id>/delete_expense",
        delete_expense,
        name="activity-delete-expense",
    ),
    path(
        "activity/<int:id>/toggle-entered",
        toggle_entered,
        name="activity-toggle-entered",
    ),
    path(
        "activity/<int:id>/toggle-entered-expense",
        toggle_entered_expense,
        name="activity-toggle-entered-expense",
    ),
    path("activity/filter", filter, name="activity-filter"),
    path("activity/filter/update", filter_update, name="activity-filter-update"),
    path(
        "activity/filter/<str:quick_filter>",
        filter_quick,
        name="activity-filter-quick",
    ),
    path(
        "activity/filter/matter/<int:id>",
        filter_matter,
        name="activity-filter-matter",
    ),
    path("activity/export", export, name="activity-export"),
]
