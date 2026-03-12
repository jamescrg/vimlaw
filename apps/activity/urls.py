from django.urls import path

from apps.activity.expenses.views import (
    expenses_add,
    expenses_bulk_update_comp,
    expenses_bulk_update_matter,
    expenses_clear_selection,
    expenses_delete,
    expenses_edit,
    expenses_export_to_csv,
    expenses_filter,
    expenses_filter_quick,
    expenses_filter_user,
    expenses_index,
    expenses_list,
    expenses_select_all,
    expenses_toggle_entered,
    expenses_toggle_select,
    order_by_expenses,
)
from apps.activity.labels.views import (
    add_label,
    add_label_to,
    bulk_apply_label_expenses,
    bulk_apply_label_time,
    delete_label,
    edit_label,
    labels_apply_modal,
    labels_create_and_apply,
    labels_index,
    labels_list,
    labels_search,
    remove_label_from,
)
from apps.activity.time.views import (
    abbreviation_code_add,
    abbreviation_code_delete,
    abbreviation_code_edit,
    abbreviation_codes_json,
    abbreviation_codes_list,
    abbreviation_codes_reference,
    order_by_time,
    set_rate,
    time_add,
    time_bulk_update_comp,
    time_bulk_update_matter,
    time_clear_selection,
    time_delete,
    time_edit,
    time_export_to_csv,
    time_filter,
    time_filter_matter,
    time_filter_quick,
    time_filter_user,
    time_index,
    time_list,
    time_select_all,
    time_toggle_entered,
    time_toggle_select,
)

app_name = "activity"

urlpatterns = [
    path("activity/", time_index, name="time-index"),
    path("activity/list/", time_list, name="time-list"),
    path("activity/time/add", time_add, name="time-add"),
    path("activity/time/add/<int:id>/<str:request_app>", time_add, name="time-add"),
    path("activity/time/<int:id>/edit", time_edit, name="time-edit"),
    path("activity/time/set-rate/<int:matter_id>", set_rate, name="set-rate"),
    path("activity/time/export/<str:format>", time_export_to_csv, name="time-export"),
    path("activity/time/<int:id>/delete", time_delete, name="time-delete"),
    path(
        "activity/time/<int:id>/toggle-entered",
        time_toggle_entered,
        name="time-toggle-entered",
    ),
    path("activity/time/filter", time_filter, name="time-filter"),
    path(
        "activity/time/filter/quick/<str:quick_filter>",
        time_filter_quick,
        name="time-filter-quick",
    ),
    path(
        "activity/time/filter/matter/<int:matter_id>",
        time_filter_matter,
        name="time-filter-matter",
    ),
    path(
        "activity/time/filter/user/<int:user_id>/",
        time_filter_user,
        name="time-filter-user",
    ),
    path(
        "activity/time/filter/order_by/<str:order>", order_by_time, name="time-order-by"
    ),
    # Selection and bulk action URLs for time entries
    path(
        "activity/time/<int:entry_id>/toggle-select",
        time_toggle_select,
        name="time-toggle-select",
    ),
    path("activity/time/select-all", time_select_all, name="time-select-all"),
    path(
        "activity/time/clear-selection",
        time_clear_selection,
        name="time-clear-selection",
    ),
    path(
        "activity/time/bulk/update-matter",
        time_bulk_update_matter,
        name="time-bulk-update-matter",
    ),
    path(
        "activity/time/bulk/update-comp",
        time_bulk_update_comp,
        name="time-bulk-update-comp",
    ),
    # Abbreviation code management URLs
    path("activity/time/codes/", abbreviation_codes_list, name="codes-list"),
    path("activity/time/codes/add/", abbreviation_code_add, name="codes-add"),
    path(
        "activity/time/codes/<int:id>/edit/", abbreviation_code_edit, name="codes-edit"
    ),
    path(
        "activity/time/codes/<int:id>/delete/",
        abbreviation_code_delete,
        name="codes-delete",
    ),
    path("activity/time/codes/json/", abbreviation_codes_json, name="codes-json"),
    path(
        "activity/time/codes/reference/",
        abbreviation_codes_reference,
        name="codes-reference",
    ),
    path("activity/expenses/", expenses_index, name="expenses-index"),
    path("activity/expenses/list/", expenses_list, name="expenses-list"),
    path("activity/expenses/add", expenses_add, name="expenses-add"),
    path(
        "activity/expenses/add/<int:id>/<str:request_app>",
        expenses_add,
        name="expenses-add",
    ),
    path("activity/expenses/<int:id>/edit", expenses_edit, name="expenses-edit"),
    path(
        "activity/expenses/export/<str:format>",
        expenses_export_to_csv,
        name="expenses-export",
    ),
    path("activity/expenses/<int:id>/delete", expenses_delete, name="expenses-delete"),
    path(
        "activity/expenses/<int:id>/toggle-entered",
        expenses_toggle_entered,
        name="expenses-toggle-entered",
    ),
    path("activity/expenses/filter/", expenses_filter, name="expenses-filter"),
    path(
        "activity/expenses/filter/quick/<str:quick_filter>",
        expenses_filter_quick,
        name="expenses-filter-quick",
    ),
    path(
        "activity/expenses/filter/user/<int:user_id>/",
        expenses_filter_user,
        name="expenses-filter-user",
    ),
    path(
        "activity/expenses/filter/order_by/<str:order>",
        order_by_expenses,
        name="expenses-order-by",
    ),
    # Selection and bulk action URLs for expense entries
    path(
        "activity/expenses/<int:entry_id>/toggle-select",
        expenses_toggle_select,
        name="expenses-toggle-select",
    ),
    path(
        "activity/expenses/select-all", expenses_select_all, name="expenses-select-all"
    ),
    path(
        "activity/expenses/clear-selection",
        expenses_clear_selection,
        name="expenses-clear-selection",
    ),
    path(
        "activity/expenses/bulk/update-matter",
        expenses_bulk_update_matter,
        name="expenses-bulk-update-matter",
    ),
    path(
        "activity/expenses/bulk/update-comp",
        expenses_bulk_update_comp,
        name="expenses-bulk-update-comp",
    ),
    # Labels subtab
    path("activity/labels/", labels_index, name="labels-index"),
    path("activity/labels/list/", labels_list, name="labels-list"),
    path("activity/labels/add/", add_label, name="labels-add"),
    path("activity/labels/<int:label_id>/edit/", edit_label, name="labels-edit"),
    path("activity/labels/<int:label_id>/delete/", delete_label, name="labels-delete"),
    # Label application to entries
    path(
        "activity/labels/apply/<str:object_type>/<int:object_id>/",
        labels_apply_modal,
        name="labels-apply-modal",
    ),
    path(
        "activity/labels/search/<str:object_type>/<int:object_id>/",
        labels_search,
        name="labels-search",
    ),
    path(
        "activity/labels/add-to/<str:object_type>/<int:object_id>/",
        add_label_to,
        name="labels-add-to",
    ),
    path(
        "activity/labels/remove-from/<str:object_type>/<int:object_id>/",
        remove_label_from,
        name="labels-remove-from",
    ),
    path(
        "activity/labels/create-and-apply/<str:object_type>/<int:object_id>/",
        labels_create_and_apply,
        name="labels-create-and-apply",
    ),
    # Bulk label actions
    path(
        "activity/time/bulk/apply-labels",
        bulk_apply_label_time,
        name="time-bulk-apply-labels",
    ),
    path(
        "activity/expenses/bulk/apply-labels",
        bulk_apply_label_expenses,
        name="expenses-bulk-apply-labels",
    ),
]
