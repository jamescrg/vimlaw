from django.urls import path

from apps.matters import (
    views_activity as matters_activity,
    views_contacts as matters_contacts,
    views_events as matters_events,
    views_timeline as matters_timeline,
)
from apps.matters.views import (
    add,
    delete,
    detail,
    edit,
    edit_description,
    filter,
    filter_quick,
    index,
    order_by,
    print,
)

from .proceedings import views as matters_proceedings
from .rates import views as matters_rates
from .settlement import views as matters_settlement

app_name = "matters"

urlpatterns = [
    # Generic
    path("matters/", index, name="list"),
    path("matters/<int:id>", detail, name="detail"),
    path("matters/add", add, name="add"),
    path("matters/<int:id>/edit", edit, name="edit"),
    path("matters/<int:id>/delete", delete, name="delete"),
    path(
        "matters/<int:id>/edit-description",
        edit_description,
        name="edit-description",
    ),
    path("matters/<int:id>/print", print, name="print"),
    # Matters Contacts
    path("matters/<int:id>/contacts", matters_contacts.index, name="contacts"),
    path(
        "matters/<int:id>/contacts/assign",
        matters_contacts.assign,
        name="contacts-assign",
    ),
    path(
        "matters/<int:id>/contacts/assign/results",
        matters_contacts.assign_results,
        name="contacts-assign-results",
    ),
    path(
        "matters/<int:matter_id>/assign/<int:contact_id>",
        matters_contacts.assign_role,
        name="contacts-assign-role",
    ),
    path(
        "matters/assign/store",
        matters_contacts.assign_store,
        name="contacts-assign-store",
    ),
    path(
        "matters/assign/<id>/edit",
        matters_contacts.assign_edit,
        name="contacts-assign-edit",
    ),
    path(
        "matters/assign/<id>/update",
        matters_contacts.assign_update,
        name="contacts-assign-update",
    ),
    path(
        "matters/assign/<id>/delete",
        matters_contacts.assign_delete,
        name="contacts-assign-delete",
    ),
    # Matters Rates
    path("matters/<int:id>/rates", matters_rates.index, name="rates"),
    path(
        "matters/<int:id>/rates/add",
        matters_rates.add,
        name="rates-add",
    ),
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
    # Matters Activity
    path("matters/<int:id>/activity", matters_activity.index, name="activity"),
    # events
    path("matters/<int:id>/events", matters_events.index, name="events"),
    # proceedings
    path(
        "matters/<int:id>/proceedings",
        matters_proceedings.index,
        name="proceedings",
    ),
    path(
        "matters/<int:id>/proceedings/add",
        matters_proceedings.add,
        name="proceedings-add",
    ),
    path(
        "matters/<int:id>/proceedings/<int:proceeding_id>/edit",
        matters_proceedings.edit,
        name="proceedings-edit",
    ),
    path(
        "matters/<int:matter_id>/proceedings/<int:proceeding_id>/delete",
        matters_proceedings.delete,
        name="proceedings-delete",
    ),
    # Matters Settlement
    path(
        "matters/<int:id>/settlement",
        matters_settlement.index,
        name="settlement",
    ),
    path(
        "matters/<int:id>/settlement/add",
        matters_settlement.add,
        name="settlement-add",
    ),
    path(
        "matters/<int:id>/settlement/<int:entry_id>/edit",
        matters_settlement.edit,
        name="settlement-edit",
    ),
    path(
        "matters/<int:matter_id>/settlement/<int:entry_id>/delete",
        matters_settlement.delete,
        name="settlement-delete",
    ),
    # Matters Timeline
    path("matters/<int:id>/timeline", matters_timeline.index, name="timeline"),
    path(
        "matters/<int:id>/timeline/add",
        matters_timeline.add,
        name="timeline-add",
    ),
    path(
        "matters/<int:id>/timeline/<int:fact_id>/edit",
        matters_timeline.edit,
        name="timeline-edit",
    ),
    path(
        "matters/<int:matter_id>/timeline/<int:fact_id>/delete",
        matters_timeline.delete,
        name="timeline-delete",
    ),
    path(
        "matters/<int:id>/timeline/print",
        matters_timeline.print,
        name="timeline-print",
    ),
    path(
        "matters/filter-matters",
        filter,
        name="filter-matters",
    ),
    path(
        "matters/order-by/<str:order>",
        order_by,
        name="order-by",
    ),
    path(
        "matters/filter-quick/<str:quick_filter>/",
        filter_quick,
        name="filter-quick",
    ),
]
