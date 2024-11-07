from django.urls import path

from apps.folders.views import delete, insert, select, update

app_name = "folders"

urlpatterns = [
    path("folders/<int:id>/<str:app>/<str:action_type>", select, name="list"),
    path("folders/insert/<str:app>/<str:action_type>", insert, name="insert"),
    path("folders/update/<int:id>/<str:app>/<str:action_type>", update, name="update"),
    path("folders/delete/<int:id>/<str:app>/<str:action_type>", delete, name="delete"),
]
