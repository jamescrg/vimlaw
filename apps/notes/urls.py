from django.urls import path

from . import views

app_name = "notes"

urlpatterns = [
    # List views
    path("notes/", views.notes_index, name="index"),
    path("notes/list/", views.notes_list, name="list"),
    path("notes/add/", views.notes_add, name="add"),
    path("notes/filter/", views.notes_filter, name="filter"),
    path("notes/filter/keyword/", views.notes_filter_keyword, name="filter-keyword"),
    path(
        "notes/filter/category/<str:category>/",
        views.notes_filter_category,
        name="filter-category",
    ),
    path(
        "notes/filter/category/",
        views.notes_filter_category_clear,
        name="filter-category-clear",
    ),
    path(
        "notes/filter/topic/<str:topic>/",
        views.notes_filter_topic,
        name="filter-topic",
    ),
    path(
        "notes/filter/topic/",
        views.notes_filter_topic_clear,
        name="filter-topic-clear",
    ),
    path(
        "notes/filter/importance/<int:importance>/",
        views.notes_filter_importance,
        name="filter-importance",
    ),
    path("notes/order-by/<str:order>/", views.notes_order_by, name="order-by"),
    path(
        "notes/<int:note_id>/category/<str:value>/",
        views.note_category,
        name="note-category",
    ),
    path(
        "notes/<int:note_id>/importance/<int:value>/",
        views.note_importance,
        name="note-importance",
    ),
    # Editor views
    path("notes/<int:note_id>/", views.note_view, name="note-view"),
    path(
        "notes/<int:note_id>/content-partial/",
        views.note_content_partial,
        name="note-content-partial",
    ),
    path("notes/<int:note_id>/edit/", views.note_edit, name="edit"),
    path("notes/<int:note_id>/move/", views.note_move, name="note-move"),
    path("notes/<int:note_id>/delete/", views.note_delete, name="delete"),
    path("notes/<int:note_id>/content/", views.note_content, name="note-content"),
    path("notes/<int:note_id>/autosave/", views.note_autosave, name="note-autosave"),
    path("notes/<int:note_id>/title/", views.note_title, name="note-title"),
    path(
        "notes/<int:note_id>/sidebar/sort/<str:sort_key>/",
        views.sidebar_sort,
        name="note-sidebar-sort",
    ),
    path("notes/shortcuts/", views.notes_shortcuts, name="notes-shortcuts"),
    path(
        "notes/<int:note_id>/import-modal/",
        views.note_import_modal,
        name="note-import-modal",
    ),
    path(
        "notes/<int:note_id>/reference-search/",
        views.reference_search,
        name="note-reference-search",
    ),
    path(
        "notes/<int:note_id>/reference-citations/",
        views.reference_citations,
        name="note-citations",
    ),
    # Note folder views
    path(
        "notes/folders/select/<int:folder_id>/",
        views.note_folder_select,
        name="folder-select",
    ),
    path("notes/folders/unsorted/", views.note_folder_unsorted, name="folder-unsorted"),
    path("notes/folders/all/", views.note_folder_all, name="folder-all"),
    path("notes/folders/add/", views.note_folder_add, name="folder-add"),
    path(
        "notes/folders/edit/<int:folder_id>",
        views.note_folder_edit,
        name="folder-edit",
    ),
    path(
        "notes/folders/delete/<int:folder_id>/confirm",
        views.note_folder_delete_confirm,
        name="folder-delete-confirm",
    ),
    path(
        "notes/folders/delete/<int:folder_id>",
        views.note_folder_delete,
        name="folder-delete",
    ),
    path(
        "notes/folders/move/<int:folder_id>/",
        views.note_folder_move,
        name="folder-move",
    ),
    path(
        "notes/folders/toggle/<int:folder_id>/",
        views.note_folder_toggle_expand,
        name="folder-toggle",
    ),
]
