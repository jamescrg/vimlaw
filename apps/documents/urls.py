from django.urls import path

from apps.documents.views import (
    documents_filter,
    documents_list,
    documents_sort,
    download_document,
    index,
)

app_name = "documents"

urlpatterns = [
    path("documents/", index, name="index"),
    path("documents/list/", documents_list, name="list"),
    path("documents/filter/", documents_filter, name="filter"),
    path("documents/sort/<str:order>/", documents_sort, name="sort"),
    path("documents/download/<int:document_id>/", download_document, name="download"),
]
