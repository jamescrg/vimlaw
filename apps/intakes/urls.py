from django.urls import path

from apps.intakes.api_views import receive_inquiry, receive_intake, search_intakes
from apps.intakes.inbound import mailgun_inbound
from apps.intakes.views import (
    add,
    add_note,
    delete,
    delete_note,
    detail,
    detail_index,
    edit,
    edit_note,
    intake_edit_importance,
    intake_edit_practice_area,
    intake_edit_status,
    intake_filter,
    intakes_index,
    intakes_list,
    order_by,
    quick_filter_all,
    quick_filter_status,
    value_display,
    value_edit,
    value_update,
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
    path(
        "intakes/edit-importance/<int:pk>/<int:importance>",
        intake_edit_importance,
        name="edit-importance",
    ),
    path(
        "intakes/edit-practice-area/<int:pk>/<int:practice_area_id>",
        intake_edit_practice_area,
        name="edit-practice-area",
    ),
    path("intakes/<int:pk>/value-edit/", value_edit, name="value-edit"),
    path("intakes/<int:pk>/value-update/", value_update, name="value-update"),
    path("intakes/<int:pk>/value-display/", value_display, name="value-display"),
    path("api/receive-inquiry/", receive_inquiry, name="api-receive-inquiry"),
    path("api/receive-intake/", receive_intake, name="api-receive-intake"),
    path("api/intakes/search/", search_intakes, name="api-search-intakes"),
    path("api/inbound-email/", mailgun_inbound, name="api-inbound-email"),
]
