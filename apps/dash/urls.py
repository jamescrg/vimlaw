from django.urls import path

from apps.dash.agenda import (
    agenda_discard,
    agenda_messages,
    agenda_send,
    agenda_window,
)
from apps.dash.views import (
    dash_index,
    events_section,
    set_wip_period,
    wip_section,
)

app_name = "dash"

urlpatterns = [
    path("dash/", dash_index, name="index"),
    path("dash/agenda/", agenda_window, name="agenda"),
    path("dash/agenda/send", agenda_send, name="agenda-send"),
    path("dash/agenda/messages", agenda_messages, name="agenda-messages"),
    path("dash/agenda/discard", agenda_discard, name="agenda-discard"),
    path("dash/events/", events_section, name="events-section"),
    path("dash/wip/", wip_section, name="wip-section"),
    path("dash/wip/period/<str:period>/", set_wip_period, name="wip-period"),
]
