from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.folders.folders import get_list_data
from apps.folders.forms import FolderForm
from apps.folders.models import Folder


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

    saved_folder = request.session["contacts_selected_folder_id"]
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
def add(request):
    if request.method == "POST":
        form = FolderForm(request.POST)
        if form.is_valid():
            folder = form.save(commit=False)
            folder.app = "contacts"
            folder.save()
            context = get_list_data(request)
            response = render(request, "folders/list.html", context)
            response.status_code = 202  # This will trigger modal close
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
            response.status_code = 202  # This will trigger modal close
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
def delete(request, folder_id):
    folder = get_object_or_404(Folder, pk=folder_id)
    folder.delete()

    if request.session.get("contacts_selected_folder_id") == folder_id:
        del request.session["contacts_selected_folder_id"]

    context = get_list_data(request)
    response = render(request, "folders/list.html", context)
    response.status_code = 202  # This will trigger modal close
    return response
