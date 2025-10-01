from django.urls import path

from apps.documents.views import (
    add_label,
    delete_label,
    documents_add,
    documents_delete,
    documents_edit,
    documents_filter,
    documents_filter_label,
    documents_filter_matter,
    documents_list,
    documents_sort,
    download_document,
    edit_label,
    get_proceedings_and_labels,
    index,
    labels_filter,
    labels_index,
    labels_list,
    labels_sort,
    toggle_document_select,
)

app_name = "documents"

urlpatterns = [
    # Documents
    path("documents/", index, name="index"),
    path("documents/list/", documents_list, name="list"),
    path("documents/add/", documents_add, name="add"),
    path("documents/add/<int:matter_id>/", documents_add, name="add-with-matter"),
    path("documents/edit/<int:document_id>/", documents_edit, name="edit"),
    path("documents/delete/<int:document_id>/", documents_delete, name="delete"),
    path("documents/filter/", documents_filter, name="filter"),
    path(
        "documents/filter/matter/<int:matter_id>/",
        documents_filter_matter,
        name="filter-matter",
    ),
    path(
        "documents/filter/label/<int:label_id>/",
        documents_filter_label,
        name="filter-label",
    ),
    path("documents/sort/<str:order>/", documents_sort, name="sort"),
    path("documents/download/<int:document_id>/", download_document, name="download"),
    path(
        "documents/get-proceedings-and-labels/",
        get_proceedings_and_labels,
        name="get-proceedings-and-labels",
    ),
    # Labels
    path("documents/labels/", labels_index, name="labels-index"),
    path("documents/labels/list/", labels_list, name="labels-list"),
    path("documents/labels/add/", add_label, name="add-label"),
    path("documents/labels/edit/<int:label_id>/", edit_label, name="edit-label"),
    path("documents/labels/delete/<int:label_id>/", delete_label, name="delete-label"),
    path("documents/labels/filter/", labels_filter, name="filter-labels"),
    path("documents/labels/sort/<str:order>/", labels_sort, name="sort-labels"),
    path(
        "documents/toggle-select/<int:document_id>/",
        toggle_document_select,
        name="toggle-select",
    ),
]
