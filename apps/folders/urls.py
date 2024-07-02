from django.urls import path

from apps.folders.views import delete, insert, select, update

urlpatterns = [
    path("folders/<int:id>/<str:page>", select, name="folder-select"),
    path("folders/insert/<str:page>", insert, name="folder-insert"),
    path("folders/update/<int:id>/<str:page>", update, name="folder-update"),
    path("folders/delete/<int:id>/<str:page>", delete, name="folder-delete"),
]
