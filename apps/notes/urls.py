from django.urls import path

from . import views

app_name = "notes"

urlpatterns = [
    # List views
    path("notes/add/", views.notes_add, name="add"),
    # Editor views
    path("notes/launch/", views.notes_launch, name="launch"),
    path("notes/palette/", views.notes_search_palette, name="search-palette"),
    path("notes/<int:note_id>/", views.note_view, name="note-view"),
    path(
        "notes/<int:note_id>/content-partial/",
        views.note_content_partial,
        name="note-content-partial",
    ),
    path("notes/<int:note_id>/move/", views.note_move, name="note-move"),
    path("notes/<int:note_id>/delete/", views.note_delete, name="delete"),
    path("notes/<int:note_id>/content/", views.note_content, name="note-content"),
    path("notes/<int:note_id>/autosave/", views.note_autosave, name="note-autosave"),
    path("notes/<int:note_id>/title/", views.note_title, name="note-title"),
    path("notes/<int:note_id>/meta/", views.note_meta, name="note-meta"),
    path(
        "notes/<int:note_id>/properties/",
        views.note_properties,
        name="note-properties",
    ),
    path(
        "notes/<int:note_id>/reassign-matter/",
        views.note_reassign_matter,
        name="note-reassign-matter",
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
    path("notes/folders/add/", views.note_folder_add, name="folder-add"),
    path(
        "notes/folders/edit/<int:folder_id>",
        views.note_folder_edit,
        name="folder-edit",
    ),
    path(
        "notes/folders/rename/<int:folder_id>/",
        views.note_folder_rename,
        name="folder-rename",
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
        "notes/folders/reparent/<int:folder_id>/",
        views.note_folder_reparent,
        name="folder-reparent",
    ),
    path(
        "notes/editor/file-tree/",
        views.editor_file_tree,
        name="editor-file-tree",
    ),
]
