from django.urls import path

from apps.activity.categories.views import set_category
from apps.activity.chips import activity_toggle_chip
from apps.activity.expenses.views import (
    expenses_add,
    expenses_bulk_update_comp,
    expenses_bulk_update_matter,
    expenses_clear_selection,
    expenses_cycle_user,
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
from apps.activity.flat_fees.views import (
    flat_fees_add,
    flat_fees_bulk_update_comp,
    flat_fees_bulk_update_matter,
    flat_fees_clear_selection,
    flat_fees_cycle_user,
    flat_fees_delete,
    flat_fees_edit,
    flat_fees_export_to_csv,
    flat_fees_filter,
    flat_fees_filter_matter,
    flat_fees_filter_quick,
    flat_fees_filter_user,
    flat_fees_index,
    flat_fees_list,
    flat_fees_select_all,
    flat_fees_toggle_entered,
    flat_fees_toggle_select,
    matter_amount,
    order_by_flat_fees,
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
    time_cycle_user,
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
    trust_available,
)

app_name = "activity"

urlpatterns = [
    path("activity/", time_index, name="time-index"),
    path("activity/list/", time_list, name="time-list"),
    path("activity/time/add", time_add, name="time-add"),
    path("activity/time/add/<int:id>/<str:request_app>", time_add, name="time-add"),
    path("activity/time/<int:id>/edit", time_edit, name="time-edit"),
    path("activity/time/set-rate/<int:matter_id>", set_rate, name="set-rate"),
    path(
        "activity/time/trust-available/<int:matter_id>",
        trust_available,
        name="trust-available",
    ),
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
        "activity/chips/<int:user_id>/toggle/",
        activity_toggle_chip,
        name="toggle-chip",
    ),
    path(
        "activity/time/cycle-user/<str:direction>/",
        time_cycle_user,
        name="time-cycle-user",
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
        "activity/expenses/cycle-user/<str:direction>/",
        expenses_cycle_user,
        name="expenses-cycle-user",
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
    # Flat-fee entries
    path("activity/flat-fees/", flat_fees_index, name="flat-fees-index"),
    path("activity/flat-fees/list/", flat_fees_list, name="flat-fees-list"),
    path("activity/flat-fees/add", flat_fees_add, name="flat-fees-add"),
    path(
        "activity/flat-fees/add/<int:id>/<str:request_app>",
        flat_fees_add,
        name="flat-fees-add",
    ),
    path("activity/flat-fees/<int:id>/edit", flat_fees_edit, name="flat-fees-edit"),
    path(
        "activity/flat-fees/matter-amount/<int:matter_id>",
        matter_amount,
        name="flat-fees-matter-amount",
    ),
    path(
        "activity/flat-fees/export/<str:format>",
        flat_fees_export_to_csv,
        name="flat-fees-export",
    ),
    path(
        "activity/flat-fees/<int:id>/delete",
        flat_fees_delete,
        name="flat-fees-delete",
    ),
    path(
        "activity/flat-fees/<int:id>/toggle-entered",
        flat_fees_toggle_entered,
        name="flat-fees-toggle-entered",
    ),
    path("activity/flat-fees/filter", flat_fees_filter, name="flat-fees-filter"),
    path(
        "activity/flat-fees/filter/quick/<str:quick_filter>",
        flat_fees_filter_quick,
        name="flat-fees-filter-quick",
    ),
    path(
        "activity/flat-fees/filter/matter/<int:matter_id>",
        flat_fees_filter_matter,
        name="flat-fees-filter-matter",
    ),
    path(
        "activity/flat-fees/filter/user/<int:user_id>/",
        flat_fees_filter_user,
        name="flat-fees-filter-user",
    ),
    path(
        "activity/flat-fees/cycle-user/<str:direction>/",
        flat_fees_cycle_user,
        name="flat-fees-cycle-user",
    ),
    path(
        "activity/flat-fees/filter/order_by/<str:order>",
        order_by_flat_fees,
        name="flat-fees-order-by",
    ),
    path(
        "activity/flat-fees/<int:entry_id>/toggle-select",
        flat_fees_toggle_select,
        name="flat-fees-toggle-select",
    ),
    path(
        "activity/flat-fees/select-all",
        flat_fees_select_all,
        name="flat-fees-select-all",
    ),
    path(
        "activity/flat-fees/clear-selection",
        flat_fees_clear_selection,
        name="flat-fees-clear-selection",
    ),
    path(
        "activity/flat-fees/bulk/update-matter",
        flat_fees_bulk_update_matter,
        name="flat-fees-bulk-update-matter",
    ),
    path(
        "activity/flat-fees/bulk/update-comp",
        flat_fees_bulk_update_comp,
        name="flat-fees-bulk-update-comp",
    ),
    # Entry coding (category management lives on the matter Categories tab)
    path(
        "activity/categories/set/<str:object_type>/<int:object_id>/",
        set_category,
        name="set-category",
    ),
]
