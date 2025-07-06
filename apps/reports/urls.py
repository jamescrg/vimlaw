from django.urls import path

from .activity import views as activity
from .clients import views as clients
from .revenue import views as revenue
from .views import reports_index, reports_list

app_name = "reports"

urlpatterns = [
    # Reports general
    path("reports/", reports_index, name="index"),
    path("reports/list/", reports_list, name="list"),
    # Activity
    path("reports/activity/", activity.activity_index, name="activity-index"),
    path("reports/activity/list/", activity.activity_list, name="activity"),
    # Revenue
    path("reports/revenue/", revenue.revenue_index, name="revenue-index"),
    path("reports/revenue/list/", revenue.revenue_list, name="revenue"),
    # Clients
    path("reports/clients/", clients.clients_index, name="clients-index"),
    path("reports/clients/list/", clients.clients_list, name="clients"),
    path("reports/clients/filter/", clients.clients_filter, name="clients-filter"),
]
