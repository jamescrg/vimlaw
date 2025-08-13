from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404

import apps.contacts.google as google
from apps.contacts.models import Contact
from apps.folders.models import CLIENT_FOLDERS, Folder
from apps.matters.models import Matter, Relationship
from apps.trust.models import Transaction


def get_list_data(request):

    folders = Folder.objects.filter(app="contacts").order_by("name")
    client_status = request.session.get("contacts_client_status")
    selected_folder_id = request.session.get("contacts_selected_folder_id")

    if selected_folder_id:
        selected_folder = get_object_or_404(Folder, pk=selected_folder_id)
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

    if request.session.get("selected_contact_id"):
        selected_contact_id = request.session["selected_contact_id"]

        try:
            selected_contact = Contact.objects.get(pk=selected_contact_id)
        except ObjectDoesNotExist:
            selected_contact = None

        relationships = Relationship.objects.filter(contact=selected_contact).order_by(
            "-matter__status", "matter__name"
        )

        # For each matter this contact is related to, add a static relationship object
        related_matters = Matter.objects.filter(client=selected_contact)

        for matter in related_matters:
            relationship = Relationship(contact=selected_contact, matter=matter)

            relationships = list(relationships)
            relationships.append(relationship)
    else:
        selected_contact = None
        relationships = None

    if google.check_credentials():
        google_logged_in = True
    else:
        google_logged_in = False

    trust = False
    if selected_contact:
        if Transaction.objects.filter(contact=selected_contact).exists():
            trust = True

    context = {
        "app": "contacts",
        "edit": False,
        "folders": folders,
        "client_status": client_status,
        "selected_folder": selected_folder,
        "contacts": contacts,
        "selected_contact": selected_contact,
        "google_logged_in": google_logged_in,
        "relationships": relationships,
        "trust": trust,
        "client_folders": CLIENT_FOLDERS,
    }

    return context
