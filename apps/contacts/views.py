from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

import apps.contacts.google as google
from apps.contacts.contacts import get_list_data
from apps.contacts.forms import ContactForm
from apps.contacts.models import Contact
from apps.folders.models import Folder
from apps.intakes.models import Intake
from apps.matters.models import Matter, Relationship, Role
from config.helpers import format_phone


@login_required
def index(request):
    context = get_list_data(request)
    return render(request, "contacts/main.html", context)


@login_required
def select(request, contact_id):
    # select a contact
    # and adjust the context to match the selected contact

    # identify the contact
    contact = get_object_or_404(Contact, pk=contact_id)

    # if the contact exists (no 404 error thrown above)
    # persist the id of the selected contact
    request.session["selected_contact_id"] = contact.id

    # check whether a the user is last viewed a list of contacts
    # based on client status, or whether the user was
    # viewing a specific folder
    client_status = request.session.get("contacts_client_status")
    folder = request.session.get("contacts_selected_folder_id")

    # if the user was viewing a list of contacts by client_status,
    # set the list to match the client_status of the contact
    if client_status and client_status != "Nonclient":
        request.session["contacts_client_status"] = contact.client_status
        request.session["contacts_selected_folder_id"] = None

    # else if the viewer was viewing a list of folders,
    # update the list to match the folder for the selected contact
    elif folder or contact.folder:
        request.session["contacts_client_status"] = None
        request.session["contacts_selected_folder_id"] = contact.folder_id

    # else if the user was viewing unsorted contacts
    # and the selected contact does not have a folder
    # remove all sorting parameters
    else:
        request.session["contacts_client_status"] = None
        request.session["contacts_selected_folder_id"] = None

    context = get_list_data(request)
    return render(request, "contacts/main.html", context)


@login_required
def add(request):

    selected_folder_id = request.session.get("contacts_selected_folder_id")
    client_status = request.session.get("contacts_client_status")

    if request.method == "POST":
        form = ContactForm(request.POST, use_required_attribute=False)
        if form.is_valid():

            # initialize the contact
            contact = form.save(commit=False)
            contact.user = request.user
            contact.phone1 = format_phone(contact.phone1)
            contact.phone2 = format_phone(contact.phone2)
            contact.phone3 = format_phone(contact.phone3)

            # link to its intake, if applicable
            intake_id = request.POST.get("intake_id")
            if intake_id:
                intake = get_object_or_404(Intake, pk=intake_id)
                contact.intake = intake

            # save the contact
            contact.save()

            # select newest contact for display
            new = Contact.objects.all().latest("id")
            return redirect("contacts:select", contact_id=new.id)

    else:
        if selected_folder_id:
            form = ContactForm(
                initial={"folder": selected_folder_id}, use_required_attribute=False
            )
        elif client_status:
            form = ContactForm(
                initial={"client_status": client_status}, use_required_attribute=False
            )
        else:
            form = ContactForm(use_required_attribute=False)

        form.fields["folder"].queryset = Folder.objects.filter(app="contacts").order_by(
            "name"
        )

        context = {
            "app": "contacts",
            "edit": False,
            "add": True,
            "action": "/contacts/add",
            "form": form,
        }

    return render(request, "contacts/form.html", context)


@login_required
def edit(request, id):

    contact = get_object_or_404(Contact, pk=id)

    if request.method == "POST":
        form = ContactForm(request.POST, instance=contact, use_required_attribute=False)
        form.fields["folder"].queryset = Folder.objects.filter(app="contacts").order_by(
            "name"
        )

        if form.is_valid():
            contact = form.save(commit=False)
            contact.user_id = request.user.id
            contact.phone1 = format_phone(contact.phone1)
            contact.phone2 = format_phone(contact.phone2)
            contact.phone3 = format_phone(contact.phone3)

            # if the contact is saved in google, update the changes in google
            if google.check_credentials() and contact.google_id:
                google.delete_contact(contact)
                contact.google_id = google.add_contact(contact)

            contact.save()

            return redirect("contacts:select", contact_id=id)

    else:
        form = ContactForm(instance=contact, use_required_attribute=False)
        form.fields["folder"].queryset = Folder.objects.filter(app="contacts").order_by(
            "name"
        )

        context = {
            "app": "contacts",
            "edit": True,
            "action": f"/contacts/{id}/edit",
            "contact": contact,
            "form": form,
        }

        return render(request, "contacts/form.html", context)


@login_required
def delete(request, id):
    # delete contact/matter relationships
    contact = get_object_or_404(Contact, pk=id)
    relationships = Relationship.objects.filter(contact=contact)
    for relationship in relationships:
        relationship.delete()

    # delete google contact
    if google.check_credentials() and contact.google_id:
        google.delete_contact(contact)

    # delete from database
    contact.delete()

    # remove as selected contact from session
    if request.session.get("selected_contact_id", False):
        del request.session["selected_contact_id"]

    return redirect("contacts:index")


@login_required
def assign(request, id):
    matters = Matter.objects.filter(status="Open").order_by("name")
    roles = Role.objects.all().order_by("name")

    context = {
        "app": "contacts",
        "action": f"/contacts/{id}/assign/store",
        "matters": matters,
        "roles": roles,
    }

    return render(request, "contacts/assign.html", context)


@login_required
def assign_store(request, id):
    matter = get_object_or_404(Matter, pk=request.POST["matter_id"])
    contact = get_object_or_404(Contact, pk=id)
    role = get_object_or_404(Role, pk=request.POST["role_id"])

    relationship = Relationship.objects.create(
        matter=matter, contact=contact, role=role
    )
    relationship.save()

    return redirect("contacts:index", contact_id=id)


@login_required
def remove(request, id):
    contact = get_object_or_404(Contact, pk=id)
    relationships = Relationship.objects.filter(contact=contact).order_by(
        "matter__name"
    )
    context = {
        "app": "contacts",
        "action": "/contacts/remove/store",
        "relationships": relationships,
    }
    return render(request, "contacts/remove.html", context)


@login_required
def remove_store(request):
    relationship = get_object_or_404(Relationship, pk=request.POST["relationship_id"])
    contact_id = relationship.contact.id
    relationship.delete()
    return redirect("contacts:index", contact_id=contact_id)


@login_required
def add_intake(request, id):
    intake = get_object_or_404(Intake, pk=id)

    initial_data = {
        "name": intake.name,
        "address": intake.address,
        "phone1": intake.phone,
        "phone1_label": "Mobile",
        "email": intake.email,
        "client_status": "Current",
    }

    form = ContactForm(initial=initial_data)

    folders = Folder.objects.filter(app="contacts").order_by("name")
    form.fields["folder"].queryset = folders

    google_connected = google.check_credentials()

    context = {
        "app": "contacts",
        "action_type": "db_update",
        "edit": False,
        "add": True,
        "action": "/contacts/add",
        "folders": folders,
        "selected_folder": None,
        "google_connected": google_connected,
        "form": form,
        "intake_id": id,
    }

    return render(request, "contacts/form.html", context)


@login_required
def toggle_google_sync(request, id):
    contact = get_object_or_404(Contact, pk=id)
    if contact.google_id:
        google.delete_contact(contact)
        contact.google_id = ""
    else:
        contact.google_id = google.add_contact(contact)
    contact.save()
    return redirect("contacts:index")


@login_required
def google_list(request):
    contacts = Contact.objects.all()
    # for contact in contacts:
    #     contact.google_id = ""
    #     contact.save()

    context = {
        "app": "contacts",
        "contacts": contacts,
    }

    return render(request, "contacts/google.html", context)
