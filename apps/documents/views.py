from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render

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
