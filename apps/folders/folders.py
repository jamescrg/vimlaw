from django.shortcuts import get_object_or_404

from apps.folders.models import Folder


def get_list_data(request):

    folders = Folder.objects.filter(app="contacts").order_by("name")
    client_status = request.session.get("contacts_client_status")
    selected_folder_id = request.session.get("contacts_selected_folder_id")

    if selected_folder_id:
        selected_folder = get_object_or_404(Folder, pk=selected_folder_id)
    else:
        selected_folder = None

    context = {
        "app": "contacts",
        "folders": folders,
        "client_status": client_status,
        "selected_folder": selected_folder,
    }

    return context
