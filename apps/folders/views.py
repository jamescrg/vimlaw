from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from django.shortcuts import redirect
from django.shortcuts import get_object_or_404

from apps.folders.models import Folder


@login_required
def select(request, id, page):
    user_id = request.user.id

    if page == "contacts":
        request.session["contacts_selected_folder_id"] = id
        if "selected_contact_id" in request.session:
            del request.session["selected_contact_id"]

    if page == "agenda":
        folder = get_object_or_404(Folder, pk=id)

        if folder.active == 1:
            folder.active = 0

        if folder.selected == 1:
            folder.selected = 0
        else:
            folder.selected = 1

        folder.save()

    return redirect(f"/{page}")


@login_required
def insert(request, page):
    folder = Folder()
    folder.user_id = request.user.id
    folder.page = page
    folder.name = request.POST["name"]
    folder.save()
    return redirect(f"/{page}")


@login_required
def update(request, id, page):
    folder = Folder.objects.filter(user_id=request.user.id, pk=id).get()
    folder.name = request.POST["name"]
    folder.save()
    return redirect(f"/{page}")


@login_required
def delete(request, id, page):
    folder = get_object_or_404(Folder, pk=id)
    folder.delete()

    # if deleting the selected folder, clear that from the session
    if request.session.get("contacts_selected_folder_id") == id:
        del request.session["contacts_selected_folder_id"]
    return redirect(f"/{page}")
