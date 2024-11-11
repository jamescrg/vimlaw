from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404

import apps.contacts.google as google
from apps.contacts.models import Contact
from apps.folders.models import Folder
from apps.matters.models import Relationship


def get_list_data(request):

    folders = Folder.objects.filter(app="contacts").order_by("name")
    folders = list(folders)
    folders.append({"id": 0, "name": "Unsorted"})

    if request.session.get("contacts_selected_folder_id"):
        selected_folder_id = request.session["contacts_selected_folder_id"]
        selected_folder = get_object_or_404(Folder, pk=selected_folder_id)
    else:
        selected_folder = None

    if selected_folder:
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

    else:
        selected_contact = None
        relationships = None

    if google.check_credentials():
        google_logged_in = True
    else:
        google_logged_in = False

    context = {
        "app": "contacts",
        "edit": False,
        "folders": folders,
        "selected_folder": selected_folder,
        "contacts": contacts,
        "selected_contact": selected_contact,
        "google_logged_in": google_logged_in,
        "relationships": relationships,
    }

    return context
