from django.urls import path

from apps.folders.views import add, client_status, delete, edit, select

app_name = "folders"

urlpatterns = [
    path("folders/client/<str:status>/", client_status, name="client"),
    path("folders/select/<int:folder_id>/", select, name="select"),
    path("folders/add/", add, name="add"),
    path("folders/edit/<str:folder_id>", edit, name="edit"),
    path("folders/delete/<str:folder_id>", delete, name="delete"),
]
