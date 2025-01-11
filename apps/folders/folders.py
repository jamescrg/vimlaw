from django.shortcuts import get_object_or_404

from apps.folders.models import CLIENT_FOLDERS, Folder


def get_list_data(request):
    folders = Folder.objects.filter(app="contacts").order_by("name")
    folders = list(folders)
    folders.append({"id": "unsorted", "name": "Unsorted"})

    # Real folder from database
    contact_folder_id = request.session.get("contacts_selected_folder_id")

    # Client Status folders
    client_folder_id = request.session.get("contacts_selected_client_folder_id")

    if client_folder_id:
        # Case: Client Status folder is selected
        selected_folder = None
    elif contact_folder_id:
        # Fetch real folder if real folder is selected
        selected_folder_id = request.session["contacts_selected_folder_id"]

        selected_folder = get_object_or_404(Folder, pk=selected_folder_id)
    else:
        # Case: No folder is selected
        selected_folder = None

    context = {
        "app": "contacts",
        "folders": folders,
        "selected_folder": selected_folder,
        "client_folders": CLIENT_FOLDERS,
    }

    return context
