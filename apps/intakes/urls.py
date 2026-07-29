from django.urls import path

from apps.intakes.api_views import receive_inquiry, receive_intake, search_intakes
from apps.intakes.assess import assess
from apps.intakes.chat import (
    chat_discard,
    chat_end,
    chat_messages,
    chat_send,
    chat_window,
)
from apps.intakes.client_forms.views import (
    form_builder,
    form_builder_save,
    form_submission_delete,
    form_submission_fill,
    form_submission_fill_complete,
    form_submission_fill_save,
    form_submission_link,
    form_submission_reissue,
    form_submission_resend,
    form_submission_send,
    form_submission_status,
    form_template_delete,
    form_template_duplicate,
    form_template_name_edit,
    form_template_name_update,
    form_template_new,
    form_template_preview,
    form_template_settings,
    forms_index,
    forms_list,
    intake_form_add,
    intake_forms_panel,
)
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
    path("intakes/<int:id>/assess", assess, name="assess"),
    path("intakes/<int:id>/chat/", chat_window, name="chat"),
    path("intakes/<int:id>/chat/send", chat_send, name="chat-send"),
    path("intakes/<int:id>/chat/messages", chat_messages, name="chat-messages"),
    path("intakes/<int:id>/chat/end", chat_end, name="chat-end"),
    path("intakes/<int:id>/chat/discard", chat_discard, name="chat-discard"),
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
    # Custom intake forms. These sit under intakes/ so PermissionMiddleware
    # gates them on perm_intakes; the public fill page is mounted at /form/.
    # "forms" can't be swallowed by intakes/<int:id>/ — that requires digits.
    path("intakes/forms/", forms_index, name="forms-index"),
    path("intakes/forms/list/", forms_list, name="forms-list"),
    path("intakes/forms/new/", form_template_new, name="form-template-new"),
    path("intakes/forms/<int:template_id>/", form_builder, name="form-builder"),
    path(
        "intakes/forms/<int:template_id>/save/",
        form_builder_save,
        name="form-builder-save",
    ),
    path(
        "intakes/forms/<int:template_id>/settings/",
        form_template_settings,
        name="form-template-settings",
    ),
    path(
        "intakes/forms/<int:template_id>/duplicate/",
        form_template_duplicate,
        name="form-template-duplicate",
    ),
    path(
        "intakes/forms/<int:template_id>/delete/",
        form_template_delete,
        name="form-template-delete",
    ),
    # Sending a form from an intake, and reading what came back.
    path(
        "intakes/forms/<int:template_id>/preview/",
        form_template_preview,
        name="form-template-preview",
    ),
    path(
        "intakes/forms/<int:template_id>/name/edit/",
        form_template_name_edit,
        name="form-template-name-edit",
    ),
    path(
        "intakes/forms/<int:template_id>/name/",
        form_template_name_update,
        name="form-template-name-update",
    ),
    path("intakes/<int:id>/forms/", intake_forms_panel, name="forms-panel"),
    # Two steps: add prepares the form, send hands it to the client.
    path("intakes/<int:id>/forms/add/", intake_form_add, name="form-add"),
    path(
        "intakes/forms/submissions/<int:sub_id>/send/",
        form_submission_send,
        name="form-submission-send",
    ),
    # Opened in a new tab: the paralegal fills it in with the client on the
    # phone, so it has to sit beside the intake rather than replace it.
    path(
        "intakes/forms/submissions/<int:sub_id>/fill/",
        form_submission_fill,
        name="form-submission-fill",
    ),
    path(
        "intakes/forms/submissions/<int:sub_id>/fill/save/",
        form_submission_fill_save,
        name="form-submission-fill-save",
    ),
    path(
        "intakes/forms/submissions/<int:sub_id>/fill/complete/",
        form_submission_fill_complete,
        name="form-submission-fill-complete",
    ),
    path(
        "intakes/forms/submissions/<int:sub_id>/link/",
        form_submission_link,
        name="form-submission-link",
    ),
    path(
        "intakes/forms/submissions/<int:sub_id>/resend/",
        form_submission_resend,
        name="form-submission-resend",
    ),
    path(
        "intakes/forms/submissions/<int:sub_id>/delete/",
        form_submission_delete,
        name="form-submission-delete",
    ),
    path(
        "intakes/forms/submissions/<int:sub_id>/reissue/",
        form_submission_reissue,
        name="form-submission-reissue",
    ),
    path(
        "intakes/forms/submissions/<int:sub_id>/status/<str:status>/",
        form_submission_status,
        name="form-submission-status",
    ),
    path("api/receive-inquiry/", receive_inquiry, name="api-receive-inquiry"),
    path("api/receive-intake/", receive_intake, name="api-receive-intake"),
    path("api/intakes/search/", search_intakes, name="api-search-intakes"),
    path("api/inbound-email/", mailgun_inbound, name="api-inbound-email"),
]
