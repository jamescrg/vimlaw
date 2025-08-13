from django.urls import path

from apps.documents.views import documents_list, download_document, index

app_name = "documents"

urlpatterns = [
    path("documents/", index, name="index"),
    path("documents/list/", documents_list, name="list"),
    path("documents/download/<int:document_id>/", download_document, name="download"),
]
