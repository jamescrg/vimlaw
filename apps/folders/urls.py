from django.urls import path

from apps.folders.views import delete, insert, select, update

app_name = "folders"

urlpatterns = [
    path("folders/<int:id>/<str:app>", select, name="list"),
    path("folders/insert/<str:app>", insert, name="insert"),
    path("folders/update/<int:id>/<str:app>", update, name="update"),
    path("folders/delete/<int:id>/<str:app>", delete, name="delete"),
]
