from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

import apps.contacts.google as google
from apps.contacts.models import Contact
from apps.folders.folders import get_list_data
from apps.folders.forms import FolderForm
from apps.folders.models import Folder
from apps.matters.models import Relationship


@login_required
def list(request):
    context = get_list_data(request)
    return render(request, "folders/list.html", context)


@login_required
def client_status(request, status):

    saved_status = request.session.get("contacts_client_status")
    if status == saved_status:
        request.session["contacts_client_status"] = None
    else:
        request.session["contacts_client_status"] = status

    # unset the selected folder
    request.session["contacts_selected_folder_id"] = None

    # unset the selected contact
    request.session["selected_contact_id"] = None

    return redirect("contacts:index")


@login_required
def select(request, folder_id):

    saved_folder = request.session.get("contacts_selected_folder_id")
    if folder_id == saved_folder:
        request.session["contacts_selected_folder_id"] = None
    else:
        request.session["contacts_selected_folder_id"] = folder_id

    # unset the selected client status
    request.session["contacts_client_status"] = None

    # unset the selected contact
    request.session["selected_contact_id"] = None

    return redirect("contacts:index")


@login_required
def unsorted(request):
    request.session["contacts_client_status"] = None
    request.session["contacts_selected_folder_id"] = None
    request.session["selected_contact_id"] = None
    return redirect("contacts:index")


@login_required
def add(request):
    if request.method == "POST":
        form = FolderForm(request.POST)
        if form.is_valid():
            folder = form.save(commit=False)
            folder.app = "contacts"
            folder.save()
            context = get_list_data(request)
            response = render(request, "folders/list.html", context)
            # The body swaps the refreshed list into #folders; the HX-Trigger
            # (caught in alpine-components.js) closes the modal.
            response["HX-Trigger"] = "closeModal"
            return response
    else:
        form = FolderForm()

    context = {
        "form": form,
        "action": "/folders/add/",
        "edit": False,
    }
    return render(request, "folders/form.html", context)


@login_required
def edit(request, folder_id):
    folder = get_object_or_404(Folder, pk=folder_id)

    if request.method == "POST":
        form = FolderForm(request.POST, instance=folder)
        if form.is_valid():
            form.save()
            context = get_list_data(request)
            response = render(request, "folders/list.html", context)
            # The body swaps the refreshed list into #folders; the HX-Trigger
            # (caught in alpine-components.js) closes the modal.
            response["HX-Trigger"] = "closeModal"
            return response
    else:
        form = FolderForm(instance=folder)

    context = {
        "form": form,
        "action": f"/folders/edit/{folder_id}",
        "edit": True,
        "folder": folder,
    }
    return render(request, "folders/form.html", context)


@login_required
def delete_confirm(request, folder_id):
    folder = get_object_or_404(Folder, pk=folder_id)
    contact_count = Contact.objects.filter(folder=folder).count()

    context = {
        "folder": folder,
        "contact_count": contact_count,
    }
    return render(request, "folders/delete-confirm.html", context)


@login_required
def delete(request, folder_id):
    folder = get_object_or_404(Folder, pk=folder_id)

    # Check if we should delete contacts too
    if request.GET.get("delete_contacts"):
        contacts = Contact.objects.filter(folder=folder)
        for contact in contacts:
            # Delete relationships
            Relationship.objects.filter(contact=contact).delete()
            # Delete from Google if connected
            if google.check_credentials() and contact.google_id:
                google.delete_contact(contact)
            contact.delete()

    # Clear selected contact if it was in this folder
    selected_contact_id = request.session.get("selected_contact_id")
    if selected_contact_id:
        try:
            contact = Contact.objects.get(pk=selected_contact_id)
            if contact.folder_id == folder_id:
                del request.session["selected_contact_id"]
        except Contact.DoesNotExist:
            del request.session["selected_contact_id"]

    # Clear selected folder
    if request.session.get("contacts_selected_folder_id") == folder_id:
        del request.session["contacts_selected_folder_id"]

    folder.delete()

    return HttpResponse(status=204, headers={"HX-Refresh": "true"})
