from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.folders.folders import get_list_data
from apps.folders.models import Folder


@login_required
def list(request):
    context = get_list_data(request)
    return render(request, "folders/list.html", context)


@login_required
def client_status(request, status):

    saved_status = request.session["contacts_client_status"]
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
    return render(request, "folders/add.html")


@login_required
def insert(request):
    folder = Folder()
    folder.user_id = request.user.id
    folder.name = request.POST["name"]
    folder.app = "contacts"
    if folder.name:
        folder.save()
    context = get_list_data(request)
    return render(request, "folders/list.html", context)


@login_required
def edit(request, folder_id):
    folder = get_object_or_404(Folder, pk=folder_id)
    context = {"folder": folder}
    return render(request, "folders/edit.html", context)


@login_required
def update(request, folder_id):
    folder = get_object_or_404(Folder, pk=folder_id)
    folder.name = request.POST["name"]
    folder.save()
    context = {"folder": folder}
    return render(request, "folders/folder.html", context)


@login_required
def delete(request, folder_id):
    folder = get_object_or_404(Folder, pk=folder_id)
    folder.delete()

    if request.session.get("contacts_selected_folder_id") == folder_id:
        del request.session["contacts_selected_folder_id"]

    context = get_list_data(request)
    return render(request, "folders/list.html", context)
