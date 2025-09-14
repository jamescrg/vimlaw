from django.urls import path

from apps.documents.views import (
    documents_add,
    documents_delete,
    documents_edit,
    documents_filter,
    documents_filter_matter,
    documents_list,
    documents_sort,
    download_document,
    index,
)

app_name = "documents"

urlpatterns = [
    path("documents/", index, name="index"),
    path("documents/add/", documents_add, name="add"),
    path("documents/add/<int:matter_id>/", documents_add, name="add-with-matter"),
    path("documents/edit/<int:document_id>/", documents_edit, name="edit"),
    path("documents/delete/<int:document_id>/", documents_delete, name="delete"),
    path("documents/list/", documents_list, name="list"),
    path("documents/filter/", documents_filter, name="filter"),
    path(
        "documents/filter/matter/<int:matter_id>/",
        documents_filter_matter,
        name="filter-matter",
    ),
    path("documents/sort/<str:order>/", documents_sort, name="sort"),
    path("documents/download/<int:document_id>/", download_document, name="download"),
]
