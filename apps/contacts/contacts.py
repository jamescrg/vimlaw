from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404

import apps.contacts.google as google
from apps.contacts.models import Contact
from apps.folders.models import CLIENT_FOLDERS, Folder
from apps.matters.models import Matter, Relationship
from apps.trust.models import Transaction


def get_list_data(request):
    folders = Folder.objects.filter(app="contacts").order_by("name")
    folders = list(folders)

    folders.append({"id": "unsorted", "name": "Unsorted"})

    # Real folder from database
    contact_folder_id = request.session.get("contacts_selected_folder_id")

    # Client Status folders
    client_folder_id = request.session.get("contacts_selected_client_folder_id")

    if client_folder_id:
        # Case: Client Status folder is selected
        selected_folder = None
    elif contact_folder_id:
        # Fetch real folder if real folder is selected
        selected_folder_id = request.session["contacts_selected_folder_id"]
        selected_folder = get_object_or_404(Folder, pk=selected_folder_id)
    else:
        # Case: No folder is selected
        selected_folder = None

    if selected_folder:
        contacts = Contact.objects.filter(folder_id=selected_folder_id)
    else:
        # Filter contacts based on Client Status
        if client_folder_id == "current":
            contacts = Contact.objects.filter(client_status="Current")
            selected_folder = {"id": "current", "name": "Current"}
        elif client_folder_id == "former":
            contacts = Contact.objects.filter(client_status="Former")
            selected_folder = {"id": "former", "name": "Former"}
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
        "selected_folder": selected_folder,
        "contacts": contacts,
        "selected_contact": selected_contact,
        "google_logged_in": google_logged_in,
        "relationships": relationships,
        "trust": trust,
        "client_folders": CLIENT_FOLDERS,
    }

    return context
