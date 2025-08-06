from django.urls import path

from apps.documents.views import index

app_name = "documents"

urlpatterns = [
    path("documents/", index, name="index"),
]
