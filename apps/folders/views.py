from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.folders.folders import get_list_data
from apps.folders.models import Folder


@login_required
def list(request):
    context = get_list_data(request)
    return render(request, "folders/list.html", context)


@login_required
def select(request, folder_id, folder_type):
    if folder_type == "current" or folder_type == "former":
        request.session["contacts_selected_client_folder_id"] = folder_id
        request.session["contacts_selected_folder_id"] = None
    else:
        request.session["contacts_selected_folder_id"] = folder_id
        request.session["contacts_selected_client_folder_id"] = None

    selected_contact_id = request.session.get("selected_contact_id")

    # Preserve the selected contact ID in the URL if it exists
    if selected_contact_id:
        return redirect(
            "contacts:contact-index-with-id", contact_id=selected_contact_id
        )
    else:
        return redirect("contacts:contact-index")


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
