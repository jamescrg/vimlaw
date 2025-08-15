from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render

from apps.documents.filters import DocumentsFilter
from apps.documents.get_document_data import get_document_data
from apps.documents.models import Document


@login_required
def index(request):
    documents_data = get_document_data(request)

    context = {
        "app": "documents",
    } | documents_data

    return render(request, "documents/main.html", context)


@login_required
def documents_list(request):
    documents_data = get_document_data(request)

    context = {
        "app": "documents",
    } | documents_data

    return render(request, "documents/list.html", context)


@login_required
def documents_filter(request):
    if request.method == "POST":
        request.session["documents_filter"] = request.POST

        return HttpResponse(status=204, headers={"HX-Trigger": "documentsChanged"})
    else:
        filter_data = request.session.get("documents_filter", {})

        if filter_data:
            filter = DocumentsFilter(
                filter_data,
                queryset=Document.objects.all()
                .select_related("matter", "uploaded_by")
                .order_by("-uploaded_at"),
            )
        else:
            default_filter = {"order_by": "-uploaded_at"}

            filter = DocumentsFilter(
                default_filter,
                queryset=Document.objects.all()
                .select_related("matter", "uploaded_by")
                .order_by("-uploaded_at"),
            )

        return render(request, "documents/filter.html", {"filter": filter})


@login_required
def documents_sort(request, order):
    filter_data = request.session.get("documents_filter", {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["documents_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "documentsChanged"})


@login_required
def download_document(request, document_id):
    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        return HttpResponse(status=404)

    response = HttpResponse(
        document.file,
        content_type="application/octet-stream",
    )

    response["Content-Disposition"] = (
        f'attachment; filename="{document.name}.{document.file.name.split(".")[-1]}"'
    )
    response["Content-Length"] = document.file.size

    return response
