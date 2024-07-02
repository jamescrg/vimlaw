from django.urls import path

from apps.invoicing.views import index

urlpatterns = [
    path("invoicing/", index, name="invoicing"),
]
