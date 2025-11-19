from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.agenda.collection.get_collection_data import get_collection_data


@login_required
def collection_index(request):
    collection_data = get_collection_data(request)

    context = {
        "app": "agenda",
        "subapp": "collection",
    } | collection_data

    return render(request, "agenda/collection/main.html", context)


@login_required
def collection_list(request):
    collection_data = get_collection_data(request)

    context = {
        "app": "agenda",
        "subapp": "collection",
    }

    context = context | collection_data

    return render(request, "agenda/collection/list.html", context)
