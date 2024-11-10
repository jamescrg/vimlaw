from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.folders.models import Folder


@login_required
def select(request, id, app, action_type=None):
    if action_type == "db_update":
        request.session["contacts_selected_folder_id"] = id

        if "selected_contact_id" in request.session:
            del request.session["selected_contact_id"]

        return redirect("contacts:contact-index")

    if app == "contacts":
        request.session["contacts_selected_folder_id"] = id
        if "selected_contact_id" in request.session:
            del request.session["selected_contact_id"]

        return redirect("contacts:contact-index")

    if app == "agenda":
        folder = get_object_or_404(Folder, pk=id)

        if folder.active == 1:
            folder.active = 0

        if folder.selected == 1:
            folder.selected = 0
        else:
            folder.selected = 1

        folder.save()

    return redirect("contacts:contact-index")


@login_required
def insert(request, app, action_type=None):
    folder = Folder()
    folder.user_id = request.user.id
    folder.app = app
    folder.name = request.POST["name"]
    folder.save()

    if action_type == "db_update":
        return redirect("contacts:add")

    return HttpResponse(status=204, headers={"HX-Trigger": "contactsChanged"})


@login_required
def update(request, id, app, action_type=None):
    folder = get_object_or_404(Folder, pk=id)
    folder.name = request.POST["name"]
    folder.save()

    if action_type == "db_update":
        return redirect("contacts:add")

    return render(request, "folders/single-folder.html", {"folder": folder})


@login_required
def delete(request, id, app, action_type=None):
    folder = get_object_or_404(Folder, pk=id)
    folder.delete()

    if request.session.get("contacts_selected_folder_id") == id:
        del request.session["contacts_selected_folder_id"]

    if action_type == "db_update":
        return redirect("contacts:add")

    return HttpResponse(status=204, headers={"HX-Trigger": "contactsChanged"})
