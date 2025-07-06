from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

import apps.contacts.google as google
from apps.contacts.contacts import get_list_data
from apps.contacts.forms import ContactForm
from apps.contacts.models import Contact
from apps.folders.models import CLIENT_FOLDERS, Folder
from apps.intakes.models import Intake
from apps.matters.models import Matter, Relationship, Role
from config.helpers import format_phone


@login_required
def contact_index(request):
    context = get_list_data(request)
    return render(request, "contacts/main.html", context)


@login_required
def select(request, id):
    # Check if coming from reports
    from_reports = request.GET.get("from") == "reports"

    if from_reports:
        # Set client status filter to "current" when coming from reports
        request.session["contacts_selected_client_folder_id"] = "current"
        request.session["contacts_selected_folder_id"] = None
    else:
        # Normal behavior
        # Real folder from database
        contact_folder_id = request.session.get(
            "contacts_selected_folder_id", "unsorted"
        )

        # Client Status folders
        client_folder_id = request.session.get("contacts_selected_client_folder_id")

        if client_folder_id:
            request.session["contacts_selected_folder_id"] = client_folder_id
        else:
            request.session["contacts_selected_folder_id"] = contact_folder_id

    request.session["selected_contact_id"] = id

    return redirect("contacts:contact-index")


@login_required
def add(request):
    folders = Folder.objects.filter(app="contacts").order_by("name")

    contact_folder_id = request.session.get("contacts_selected_folder_id")

    client_folder_id = request.session.get("contacts_selected_client_folder_id")

    if client_folder_id:
        selected_folder = None
    elif contact_folder_id:
        selected_folder_id = request.session["contacts_selected_folder_id"]
        selected_folder = get_object_or_404(Folder, pk=selected_folder_id)
    else:
        selected_folder = None

    if request.method == "POST":
        form = ContactForm(request.POST, use_required_attribute=False)
        if form.is_valid():
            # initialize contact data
            contact = form.save(commit=False)
            contact.user = request.user
            contact.phone1 = format_phone(contact.phone1)
            contact.phone2 = format_phone(contact.phone2)
            contact.phone3 = format_phone(contact.phone3)

            intake_id = request.POST.get("intake_id")
            if intake_id:
                intake = get_object_or_404(Intake, pk=intake_id)
                contact.intake = intake

            contact.save()

            # select newest contact for user
            new = Contact.objects.all().latest("id")
            request.session["selected_contact_id"] = new.id
            request.session["contacts_selected_folder_id"] = (
                new.folder.id if new.folder else 0
            )

            return redirect("/contacts")

    # if no post data has been submitted, show the contact form
    else:
        if selected_folder:
            form = ContactForm(
                initial={"folder": selected_folder.id}, use_required_attribute=False
            )
        else:
            form = ContactForm(use_required_attribute=False)

    form.fields["folder"].queryset = Folder.objects.filter(app="contacts").order_by(
        "name"
    )

    context = {
        "app": "contacts",
        "action_type": "db_update",
        "edit": False,
        "add": True,
        "action": "/contacts/add",
        "folders": folders,
        "selected_folder": selected_folder,
        "form": form,
        "client_folders": CLIENT_FOLDERS,
    }

    return render(request, "contacts/content-form.html", context)


@login_required
def edit(request, id):
    folders = Folder.objects.filter(app="contacts").order_by("name")

    contact_folder_id = request.session.get("contacts_selected_folder_id")

    client_folder_id = request.session.get("contacts_selected_client_folder_id")

    if client_folder_id:
        selected_folder = None
    elif contact_folder_id:
        selected_folder_id = request.session["contacts_selected_folder_id"]
        selected_folder = get_object_or_404(Folder, pk=selected_folder_id)
    else:
        selected_folder = None

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

            return redirect("/contacts")

    else:
        if selected_folder:
            form = ContactForm(
                instance=contact,
                initial={"folder": selected_folder.id},
                use_required_attribute=False,
            )
        else:
            form = ContactForm(instance=contact, use_required_attribute=False)

    form.fields["folder"].queryset = Folder.objects.filter(app="contacts").order_by(
        "name"
    )

    google_connected = google.check_credentials()

    context = {
        "app": "contacts",
        "action_type": "db_update",
        "edit": True,
        "add": False,
        "action": f"/contacts/{id}/edit",
        "folders": folders,
        "selected_folder": selected_folder,
        "contact": contact,
        "google_connected": google_connected,
        "form": form,
        "client_folders": CLIENT_FOLDERS,
    }

    return render(request, "contacts/content-form.html", context)


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

    return redirect("/contacts")


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

    return redirect("/contacts")


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
    relationship.delete()
    return redirect("/contacts")


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

    return render(request, "contacts/content-form.html", context)


@login_required
def toggle_google_sync(request, id):
    contact = get_object_or_404(Contact, pk=id)
    if contact.google_id:
        google.delete_contact(contact)
        contact.google_id = ""
    else:
        contact.google_id = google.add_contact(contact)
    contact.save()
    return redirect("/contacts")


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
