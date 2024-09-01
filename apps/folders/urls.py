from django.urls import path

from apps.folders.views import delete, insert, select, update

app_name = "folders"

# fmt: off
urlpatterns = [
    path("folders/<int:id>/<str:page>", select, name="list"),
    path("folders/insert/<str:page>", insert, name="insert"),
    path("folders/update/<int:id>/<str:page>", update, name="update"),
    path("folders/delete/<int:id>/<str:page>", delete, name="delete"),
]
# fmt: on
