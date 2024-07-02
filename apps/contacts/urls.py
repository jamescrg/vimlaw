from django.urls import path

from apps.contacts.views import (
    add,
    add_intake,
    assign,
    assign_store,
    delete,
    edit,
    google_list,
    index,
    remove,
    remove_store,
    select,
    toggle_google_sync,
)

urlpatterns = [
    path("contacts/", index, name="contacts"),
    path("contacts/<int:id>", select, name="contacts-select"),
    path("contacts/add", add, name="contacts-add"),
    path("contacts/<int:id>/edit", edit, name="contacts-edit"),
    path("contacts/<int:id>/delete", delete, name="contacts-delete"),
    path("contacts/<int:id>/assign", assign, name="contacts-assign"),
    path(
        "contacts/<int:id>/assign/store",
        assign_store,
        name="contacts-assign-store",
    ),
    path("contacts/<int:id>/remove", remove, name="contacts-remove"),
    path(
        "contacts/<int:id>/remove/store",
        remove_store,
        name="contacts-remove-store",
    ),
    path("contacts/<int:id>/add_intake", add_intake, name="contacts-add-intake"),
    path(
        "contacts/<int:id>/toggle_google_sync",
        toggle_google_sync,
        name="contacts-toggle-google-sync",
    ),
    path("contacts/google_list", google_list, name="contacts-google"),
]
