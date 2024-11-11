from django.urls import path

from apps.folders.views import add, delete, edit, insert, select, update

app_name = "folders"

urlpatterns = [
    path("folders/<int:folder_id>", select, name="list"),
    path("folders/add", add, name="add"),
    path("folders/insert", insert, name="insert"),
    path("folders/edit/<int:folder_id>", edit, name="edit"),
    path("folders/update/<int:folder_id>", update, name="update"),
    path("folders/delete/<int:folder_id>", delete, name="delete"),
]
