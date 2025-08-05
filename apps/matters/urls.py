from django.urls import path

from .activity import views as activity
from .contacts import views as contacts
from .events import views as events
from .ledger import views as ledger
from .proceedings import views as proceedings
from .rates import views as matters_rates
from .settlement import views as settlement
from .timeline import views as timeline
from .views import (
    add,
    delete,
    detail,
    edit,
    edit_work_status,
    filter,
    filter_quick,
    filter_quick_status,
    matter_index,
    matter_list,
    order_by,
    print,
    update_work_status,
)

app_name = "matters"

urlpatterns = [
    # Matters, general
    path("matters/", matter_index, name="index"),
    path("matters/list/", matter_list, name="list"),
    path("matters/<int:id>", detail, name="detail"),
    path("matters/add", add, name="add"),
    path("matters/<int:id>/edit", edit, name="edit"),
    path("matters/<int:id>/delete", delete, name="delete"),
    path(
        "matters/edit-work-status/<int:matter_id>",
        edit_work_status,
        name="edit-work-status",
    ),
    path(
        "matters/<int:id>/update-work-status",
        update_work_status,
        name="update-work-status",
    ),
    path("matters/<int:id>/print", print, name="print"),
    # Contacts
    path("matters/<int:id>/contacts", contacts.index, name="contacts"),
    path("matters/<int:id>/contacts/assign", contacts.assign, name="contacts-assign"),
    path(
        "matters/<int:id>/contacts/assign/results",
        contacts.assign_results,
        name="contacts-assign-results",
    ),
    path(
        "matters/<int:matter_id>/assign/<int:contact_id>",
        contacts.assign_role,
        name="contacts-assign-role",
    ),
    path("matters/assign/store", contacts.assign_store, name="contacts-assign-store"),
    path("matters/assign/<id>/edit", contacts.assign_edit, name="contacts-assign-edit"),
    path(
        "matters/assign/<id>/update",
        contacts.assign_update,
        name="contacts-assign-update",
    ),
    path(
        "matters/assign/<id>/delete",
        contacts.assign_delete,
        name="contacts-assign-delete",
    ),
    # Rates
    path("matters/<int:id>/rates", matters_rates.rate_index, name="rate-index"),
    path("matters/<int:id>/rates/list/", matters_rates.rate_list, name="rates"),
    path("matters/<int:id>/rates/add", matters_rates.add, name="rates-add"),
    path(
        "matters/<int:id>/rates/<int:rate_id>/edit",
        matters_rates.edit,
        name="rates-edit",
    ),
    path(
        "matters/<int:matter_id>/rates/<int:rate_id>/delete",
        matters_rates.delete,
        name="rates-delete",
    ),
    # Activity
    path("matters/<int:id>/activity/", activity.activity_index, name="activity-index"),
    path("matters/<int:id>/activity/list/", activity.activity_list, name="activity"),
    # events
    path("matters/<int:id>/events/", events.events_index, name="events-index"),
    path("matters/<int:id>/events/list/", events.events_list, name="events"),
    # proceedings
    path(
        "matters/<int:id>/proceedings/",
        proceedings.proceeding_index,
        name="proceedings-index",
    ),
    path(
        "matters/<int:id>/proceedings/list/",
        proceedings.proceeding_list,
        name="proceedings",
    ),
    path("matters/<int:id>/proceedings/add", proceedings.add, name="proceedings-add"),
    path(
        "matters/<int:id>/proceedings/<int:proceeding_id>/edit",
        proceedings.edit,
        name="proceedings-edit",
    ),
    path(
        "matters/<int:matter_id>/proceedings/<int:proceeding_id>/delete",
        proceedings.delete,
        name="proceedings-delete",
    ),
    # Settlement
    path(
        "matters/<int:id>/settlement/",
        settlement.settlement_index,
        name="settlement-index",
    ),
    path(
        "matters/<int:id>/settlement/list/",
        settlement.settlement_list,
        name="settlement",
    ),
    path("matters/<int:id>/settlement/add", settlement.add, name="settlement-add"),
    path(
        "matters/<int:id>/settlement/<int:entry_id>/edit",
        settlement.edit,
        name="settlement-edit",
    ),
    path(
        "matters/<int:matter_id>/settlement/<int:entry_id>/delete",
        settlement.delete,
        name="settlement-delete",
    ),
    # Timeline
    path("matters/<int:id>/timeline/", timeline.timeline_index, name="timeline-index"),
    path("matters/<int:id>/timeline/list/", timeline.timeline_list, name="timeline"),
    path("matters/<int:id>/timeline/add", timeline.add, name="timeline-add"),
    path(
        "matters/<int:id>/timeline/<int:fact_id>/edit",
        timeline.edit,
        name="timeline-edit",
    ),
    path(
        "matters/<int:matter_id>/timeline/<int:fact_id>/delete",
        timeline.delete,
        name="timeline-delete",
    ),
    path("matters/<int:id>/timeline/print", timeline.print, name="timeline-print"),
    path("matters/<int:pk>/timeline/pdf/", timeline.timeline_pdf, name="timeline-pdf"),
    path("matters/filter", filter, name="filter"),
    path("matters/order-by/<str:order>", order_by, name="order-by"),
    path("matters/filter-quick/<str:quick_filter>/", filter_quick, name="filter-quick"),
    path(
        "matters/filter-quick-status/<str:status>",
        filter_quick_status,
        name="filter-quick-status",
    ),
    # Ledger
    path("matters/<int:id>/ledger/", ledger.ledger_index, name="ledger"),
    path("matters/<int:id>/ledger/list/", ledger.ledger_list, name="ledger-list"),
    path("matters/<int:pk>/ledger/pdf/", ledger.ledger_pdf, name="ledger-pdf"),
    path(
        "matters/<int:id>/activity-report/",
        activity.activity_report,
        name="activity-report",
    ),
]
