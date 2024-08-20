from django.urls import path

from apps.activity.views import (
    add,
    add_expense,
    delete,
    delete_expense,
    edit,
    edit_expense,
    expenses_filter,
    export,
    filter_matter,
    index,
    quick_filter_today,
    quick_filter_unbilled,
    quick_filter_user,
    set_tab,
    time_entry_filter,
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
    path("activity/export", export, name="export"),
    path(
        "activity/set-tab/<str:tab>",
        set_tab,
        name="set-tab",
    ),
    path(
        "activity/quick-filter-today/<str:tab>",
        quick_filter_today,
        name="quick-filter-today",
    ),
    path(
        "activity/quick-filter-unbilled/<str:tab>",
        quick_filter_unbilled,
        name="quick-filter-unbilled",
    ),
    path(
        "activity/quick-filter-user/<str:tab>",
        quick_filter_user,
        name="quick-filter-user",
    ),
    path(
        "activity/filter-matter/<int:matter_id>/<str:tab>",
        filter_matter,
        name="filter-matter",
    ),
    path(
        "activity/filter-time-entries/", time_entry_filter, name="filter-time-entries"
    ),
    path(
        "activity/filter-expenses/",
        expenses_filter,
        name="filter-expenses",
    ),
]
