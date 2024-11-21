from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.billing.collection.get_collection_data import get_collection_data


@login_required
def collection_index(request):
    collection_data = get_collection_data(request)

    context = {
        "app": "billing",
        "subapp": "collection",
    } | collection_data

    return render(request, "billing/collection/main.html", context)


@login_required
def collection_list(request):
    collection_data = get_collection_data(request)

    context = {
        "app": "billing",
        "subapp": "collection",
    }

    context = context | collection_data

    return render(request, "billing/collection/list.html", context)
