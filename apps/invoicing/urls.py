from django.urls import path

from apps.invoicing.views.invoice import index

app_name = "invoicing"

urlpatterns = [
    path("invoicing/", index, name="invoicing"),
]
