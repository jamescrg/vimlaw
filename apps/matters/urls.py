from django.urls import path

from apps.matters import (
    views_activity as matters_activity,
    views_contacts as matters_contacts,
    views_events as matters_events,
    views_proceedings as matters_proceedings,
    views_rates as matters_rates,
    views_settlement as matters_settlement,
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
    filter_update,
    index,
    order,
    print,
)

urlpatterns = [
    # Generic
    path("matters/", index, name="matters-list"),
    path("matters/<int:id>", detail, name="matters-detail"),
    path("matters/add", add, name="matters-add"),
    path("matters/<int:id>/edit", edit, name="matters-edit"),
    path("matters/<int:id>/delete", delete, name="matters-delete"),
    path("matters/filter", filter, name="matters-filter"),
    path("matters/filter/update", filter_update, name="matters-filter-update"),
    path(
        "matters/filter/<str:quick_filter>",
        filter_quick,
        name="matters-filter-quick",
    ),
    path("matters/sort/<str:order>", order, name="matters-sort-by"),
    path(
        "matters/<int:id>/edit-description",
        edit_description,
        name="matters-edit-description",
    ),
    path("matters/<int:id>/print", print, name="matters-print"),
    # Matters Contacts
    path("matters/<int:id>/contacts", matters_contacts.index, name="matters-contacts"),
    path(
        "matters/<int:id>/contacts/assign",
        matters_contacts.assign,
        name="matters-contacts-assign",
    ),
    path(
        "matters/<int:id>/contacts/assign/results",
        matters_contacts.assign_results,
        name="matters-contacts-assign-results",
    ),
    path(
        "matters/<int:id>/assign/<int:contact_id>",
        matters_contacts.assign_role,
        name="matters-contacts-assign-role",
    ),
    path(
        "matters/assign/store",
        matters_contacts.assign_store,
        name="matters-contacts-assign-store",
    ),
    path(
        "matters/assign/<id>/edit",
        matters_contacts.assign_edit,
        name="matters-contacts-assign-edit",
    ),
    path(
        "matters/assign/<id>/update",
        matters_contacts.assign_update,
        name="matters-contacts-assign-update",
    ),
    path(
        "matters/assign/<id>/delete",
        matters_contacts.assign_delete,
        name="matters-contacts-assign-delete",
    ),
    # Matters Rates
    path("matters/<int:id>/rates", matters_rates.index, name="matters-rates"),
    path(
        "matters/<int:id>/rates/add",
        matters_rates.add,
        name="matters-rates-add",
    ),
    path(
        "matters/<int:id>/rates/<int:rate_id>/edit",
        matters_rates.edit,
        name="matters-rates-edit",
    ),
    path(
        "matters/<int:id>/rates/<int:rate_id>/delete",
        matters_rates.delete,
        name="matters-rates-delete",
    ),
    # Matters Activity
    path("matters/<int:id>/activity", matters_activity.index, name="matters-activity"),
    # matters-events
    path("matters/<int:id>/events", matters_events.index, name="matters-events"),
    # matters-proceedings
    path(
        "matters/<int:id>/proceedings",
        matters_proceedings.index,
        name="matters-proceedings",
    ),
    path(
        "matters/<int:id>/proceedings/add",
        matters_proceedings.add,
        name="matters-proceedings-add",
    ),
    path(
        "matters/<int:id>/proceedings/<int:proceeding_id>/edit",
        matters_proceedings.edit,
        name="matters-proceedings-edit",
    ),
    path(
        "matters/<int:id>/proceedings/<int:proceeding_id>/delete",
        matters_proceedings.delete,
        name="matters-proceedings-delete",
    ),
    # Matters Settlement
    path(
        "matters/<int:id>/settlement",
        matters_settlement.index,
        name="matters-settlement",
    ),
    path(
        "matters/<int:id>/settlement/add",
        matters_settlement.add,
        name="matters-settlement-add",
    ),
    path(
        "matters/<int:id>/settlement/<int:entry_id>/edit",
        matters_settlement.edit,
        name="matters-settlement-edit",
    ),
    path(
        "matters/<int:id>/settlement/<int:entry_id>/delete",
        matters_settlement.delete,
        name="matters-settlement-delete",
    ),
    # Matters Timeline
    path("matters/<int:id>/timeline", matters_timeline.index, name="matters-timeline"),
    path(
        "matters/<int:id>/timeline/add",
        matters_timeline.add,
        name="matters-timeline-add",
    ),
    path(
        "matters/<int:id>/timeline/<int:fact_id>/edit",
        matters_timeline.edit,
        name="matters-timeline-edit",
    ),
    path(
        "matters/<int:id>/timeline/<int:fact_id>/delete",
        matters_timeline.delete,
        name="matters-timeline-delete",
    ),
    path(
        "matters/<int:id>/timeline/print",
        matters_timeline.print,
        name="matters-timeline-print",
    ),
]
