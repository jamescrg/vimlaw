from django.urls import path

from apps.management.views import clear_filters

app_name = "management"

urlpatterns = [
    path(
        "clear-filters/<str:session_key>/<str:trigger>/",
        clear_filters,
        name="clear-filters",
    ),
    path("clear-filters/<str:session_key>/", clear_filters, name="clear-filters"),
]
