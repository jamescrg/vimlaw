from django.urls import path

from .activity import views as activity
from .aging import views as aging
from .clients import views as clients
from .intakes import views as intakes
from .realization import views as realization
from .revenue import views as revenue
from .views import reports_index, reports_list
from .wip import views as wip

app_name = "reports"

urlpatterns = [
    # Reports general
    path("reports/", reports_index, name="index"),
    path("reports/list/", reports_list, name="list"),
    # Activity
    path("reports/activity/", activity.activity_index, name="activity-index"),
    path("reports/activity/list/", activity.activity_list, name="activity"),
    path("reports/activity/period/", activity.activity_period, name="activity-period"),
    # Revenue
    path("reports/revenue/", revenue.revenue_index, name="revenue-index"),
    path("reports/revenue/list/", revenue.revenue_list, name="revenue"),
    path("reports/revenue/period/", revenue.revenue_period, name="revenue-period"),
    # Realization
    path(
        "reports/realization/", realization.realization_index, name="realization-index"
    ),
    path("reports/realization/list/", realization.realization_list, name="realization"),
    path(
        "reports/realization/period/",
        realization.realization_period,
        name="realization-period",
    ),
    # Clients
    path("reports/clients/", clients.clients_index, name="clients-index"),
    path("reports/clients/list/", clients.clients_list, name="clients"),
    path("reports/clients/filter/", clients.clients_filter, name="clients-filter"),
    path(
        "reports/clients/statement/", clients.client_statement, name="client-statement"
    ),
    path(
        "reports/clients/statement/filter/",
        clients.client_statement_filter,
        name="client-statement-filter",
    ),
    path(
        "reports/clients/statement/pdf/",
        clients.client_statement_pdf,
        name="client-statement-pdf",
    ),
    # Intakes
    path("reports/intakes/", intakes.intakes_index, name="intakes-index"),
    path("reports/intakes/list/", intakes.intakes_list, name="intakes"),
    path("reports/intakes/filter/", intakes.intakes_filter, name="intakes-filter"),
    path("reports/intakes/pdf/", intakes.intakes_pdf, name="intakes-pdf"),
    # AR Aging
    path("reports/aging/", aging.aging_index, name="aging-index"),
    path("reports/aging/list/", aging.aging_list, name="aging"),
    # Unbilled WIP
    path("reports/wip/", wip.wip_index, name="wip-index"),
    path("reports/wip/list/", wip.wip_list, name="wip"),
]
