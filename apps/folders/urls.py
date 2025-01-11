from django.urls import path

from apps.folders.views import add, delete, edit, insert, select, update

app_name = "folders"

urlpatterns = [
    path("folders/<str:folder_id>/<str:folder_type>/", select, name="list"),
    path("folders/add/", add, name="add"),
    path("folders/insert/", insert, name="insert"),
    path("folders/edit/<str:folder_id>", edit, name="edit"),
    path("folders/update/<str:folder_id>", update, name="update"),
    path("folders/delete/<str:folder_id>", delete, name="delete"),
]
