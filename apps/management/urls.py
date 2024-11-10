from django.urls import path

from apps.management.pagination import change_page
from apps.management.views import clear_filters

app_name = "management"

urlpatterns = [
    # General filters
    path(
        "clear-filters/<str:session_key>/<str:trigger>/",
        clear_filters,
        name="clear-filters",
    ),
    path("clear-filters/<str:session_key>/", clear_filters, name="clear-filters"),
    # Pagination
    path(
        "pagination/change-page/<str:session_key>/<str:trigger_key>/<int:page>/",
        change_page,
        name="change-page",
    ),
]
