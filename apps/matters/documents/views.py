from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.matters.documents.get_matter_documents import get_matter_documents
from apps.matters.models import Matter


@login_required
def documents_index(request, id):
    matter = get_object_or_404(Matter, pk=id)

    document_data = get_matter_documents(request, matter)

    context = {
        "app": "matters",
        "subapp": "documents",
        "matter": matter,
    } | document_data

    return render(request, "matters/documents/main.html", context)


@login_required
def documents_list(request, id):
    matter = get_object_or_404(Matter, pk=id)

    document_data = get_matter_documents(request, matter)

    context = {
        "app": "matters",
        "subapp": "documents",
        "matter": matter,
    } | document_data

    return render(request, "matters/documents/list.html", context)


@login_required
def matters_documents_sort(request, id, order):
    filter_data = request.session.get("matters_documents_filter", {})
    filter_data["matter"] = id

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["matters_documents_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "matterDocChanged"})
