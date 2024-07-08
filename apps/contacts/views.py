from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

import apps.contacts.google as google
from apps.contacts.forms import ContactForm
from apps.contacts.models import Contact
from apps.folders.models import Folder
from apps.intakes.models import Intake
from apps.matters.models import Matter, Relationship, Role
from config.helpers import format_phone


@login_required
def index(request):
    page = "contacts"

    folders = Folder.objects.filter(page=page).order_by("name")

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
        "page": "contacts",
        "edit": False,
        "folders": folders,
        "selected_folder": selected_folder,
        "contacts": contacts,
        "selected_contact": selected_contact,
        "google_logged_in": google_logged_in,
        "relationships": relationships,
    }

    return render(request, "contacts/content.html", context)


@login_required
def select(request, id):
    contact = get_object_or_404(Contact, pk=id)

    request.session["contacts_selected_folder_id"] = contact.folder.id
    request.session["selected_contact_id"] = id

    return redirect("/contacts/")


@login_required
def add(request):
    # load initial page values (user, folders, selected folder)

    folders = Folder.objects.filter(page="contacts").order_by("name")

    if request.session.get("contacts_selected_folder_id"):
        selected_folder_id = request.session["contacts_selected_folder_id"]
        selected_folder = get_object_or_404(Folder, pk=selected_folder_id)
    else:
        selected_folder = None

    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            # initialize contact data
            contact = form.save(commit=False)
            contact.user = request.user
            contact.phone1 = format_phone(contact.phone1)
            contact.phone2 = format_phone(contact.phone2)
            contact.phone3 = format_phone(contact.phone3)

            # save contact to database with google id
            contact.save()

            # select newest contact for user
            new = Contact.objects.all().latest("id")
            request.session["selected_contact_id"] = new.id

            return redirect("/contacts")

    # if no post data has been submitted, show the contact form
    else:
        if selected_folder:
            form = ContactForm(initial={"folder": selected_folder.id})
        else:
            form = ContactForm()

    form.fields["folder"].queryset = Folder.objects.filter(page="contacts").order_by(
        "name"
    )

    google_connected = google.check_credentials()

    context = {
        "page": "contacts",
        "edit": False,
        "add": True,
        "action": "/contacts/add",
        "folders": folders,
        "selected_folder": selected_folder,
        "google_connected": google_connected,
        "form": form,
    }

    return render(request, "contacts/content.html", context)


@login_required
def edit(request, id):
    folders = Folder.objects.filter(page="contacts").order_by("name")

    if request.session.get("contacts_selected_folder_id"):
        selected_folder_id = request.session["contacts_selected_folder_id"]
        selected_folder = get_object_or_404(Folder, pk=selected_folder_id)
    else:
        selected_folder = None

    contact = get_object_or_404(Contact, pk=id)

    if request.method == "POST":
        form = ContactForm(request.POST, instance=contact)
        form.fields["folder"].queryset = Folder.objects.filter(
            page="contacts"
        ).order_by("name")

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
            form = ContactForm(instance=contact, initial={"folder": selected_folder.id})
        else:
            form = ContactForm(instance=contact)

    form.fields["folder"].queryset = Folder.objects.filter(page="contacts").order_by(
        "name"
    )

    google_connected = google.check_credentials()

    context = {
        "page": "contacts",
        "edit": True,
        "add": False,
        "action": f"/contacts/{id}/edit",
        "folders": folders,
        "selected_folder": selected_folder,
        "contact": contact,
        "google_connected": google_connected,
        "form": form,
    }

    return render(request, "contacts/content.html", context)


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
    matters = Matter.objects.filter(Q(status="Open") | Q(status="Pending")).order_by(
        "name"
    )
    roles = Role.objects.all().order_by("name")
    context = {
        "page": "contacts",
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
        "page": "contacts",
        "action": f"/contacts/{id}/remove/store",
        "relationships": relationships,
    }

    return render(request, "contacts/remove.html", context)


@login_required
def remove_store(request, id):
    relationship = get_object_or_404(Relationship, pk=request.POST["relationship_id"])
    relationship.delete()
    return redirect("/contacts")


@login_required
def add_intake(request, id):
    # get the intake to add
    intake = get_object_or_404(Intake, pk=id)

    try:
        contact = Contact.objects.filter(intake=intake).get()
    except ObjectDoesNotExist:
        contact = None

    if not contact:
        # create a contact and load it with the intake data, then save it
        contact = Contact()
        contact.user_id = request.user.id
        contact.folder_id = 313
        contact.name = intake.name
        contact.address = intake.address
        contact.phone1 = intake.phone
        contact.phone1_label = "Mobile"
        contact.email = intake.email
        contact.intake = intake

        # add to google account
        if google.check_credentials():
            contact.google_id = google.add_contact(contact)

        contact.save()

        # select newest contact for user
        new = Contact.objects.all().latest("id")
        request.session["selected_contact_id"] = new.id

    # redirect to the edit form
    return redirect(f"/contacts/{contact.id}/edit")


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
        "page": "contacts",
        "contacts": contacts,
    }

    return render(request, "contacts/google.html", context)
