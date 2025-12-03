from django.core.exceptions import ObjectDoesNotExist

import apps.contacts.google as google
from apps.contacts.models import Contact
from apps.folders.models import CLIENT_FOLDERS, Folder
from apps.matters.models import Matter, Relationship
from apps.trust.models import Transaction
from apps.trust.trust import get_confirmed_client_balance, get_pending_client_balance


def get_list_data(request):

    folders = Folder.objects.filter(app="contacts").order_by("name")
    client_status = request.session.get("contacts_client_status")
    selected_folder_id = request.session.get("contacts_selected_folder_id")

    if selected_folder_id:
        try:
            selected_folder = Folder.objects.get(pk=selected_folder_id)
        except Folder.DoesNotExist:
            selected_folder = None
            del request.session["contacts_selected_folder_id"]
    else:
        selected_folder = None

    # if a contact has both a client_status and a folder
    # pull the list of contacts matching the client_status
    # otherwise pull the list of contacts matching the folder
    # if neither value is set, get all contacts without a folder
    if client_status:
        contacts = Contact.objects.filter(client_status=client_status)
    elif selected_folder:
        contacts = Contact.objects.filter(folder_id=selected_folder_id)
    else:
        contacts = Contact.objects.filter(folder_id__isnull=True)

    contacts = contacts.order_by("name")

    selected_contact = None
    relationships = None
    selected_contact_not_found = False

    if request.session.get("selected_contact_id"):
        selected_contact_id = request.session["selected_contact_id"]

        try:
            selected_contact = Contact.objects.get(pk=selected_contact_id)
        except ObjectDoesNotExist:
            selected_contact = None
            selected_contact_not_found = True
            del request.session["selected_contact_id"]

        if selected_contact:
            relationships = list(Relationship.objects.filter(contact=selected_contact))

            # For each matter this contact is related to, add a static relationship object
            related_matters = Matter.objects.filter(client=selected_contact)

            for matter in related_matters:
                relationship = Relationship(contact=selected_contact, matter=matter)
                relationships.append(relationship)

            # Group and sort relationships by status
            # Order: Open, Pending, Complete/Closed
            # Within each group, sort by matter name ascending
            open_relationships = sorted(
                [r for r in relationships if r.matter.status == "Open"],
                key=lambda r: r.matter.name,
            )
            pending_relationships = sorted(
                [r for r in relationships if r.matter.status == "Pending"],
                key=lambda r: r.matter.name,
            )
            complete_relationships = sorted(
                [r for r in relationships if r.matter.status in ["Complete", "Closed"]],
                key=lambda r: r.matter.name,
            )

            # Combine in the desired order
            relationships = (
                open_relationships + pending_relationships + complete_relationships
            )

    if google.check_credentials():
        google_logged_in = True
    else:
        google_logged_in = False

    trust = False
    confirmed_balance = 0
    pending_balance = 0
    if selected_contact:
        if Transaction.objects.filter(contact=selected_contact).exists():
            trust = True
            confirmed_balance = get_confirmed_client_balance(selected_contact.id)
            pending_balance = get_pending_client_balance(selected_contact.id)

    context = {
        "app": "contacts",
        "edit": False,
        "folders": folders,
        "client_status": client_status,
        "selected_folder": selected_folder,
        "contacts": contacts,
        "selected_contact": selected_contact,
        "selected_contact_not_found": selected_contact_not_found,
        "google_logged_in": google_logged_in,
        "relationships": relationships,
        "trust": trust,
        "confirmed_balance": confirmed_balance,
        "pending_balance": pending_balance,
        "client_folders": CLIENT_FOLDERS,
    }

    return context
