from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render

from apps.documents.filters import DocumentsFilter
from apps.documents.forms import DocumentsForm
from apps.documents.get_document_data import get_document_data
from apps.documents.models import Document
from apps.matters.models import Matter


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
def documents_filter_matter(request, matter_id):
    filter_data = request.session.get("documents_filter", {})
    filter_data["matter"] = matter_id

    request.session["documents_filter"] = filter_data

    return redirect("documents:list")


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
def documents_add(request, matter_id=None):
    if request.method == "POST":
        form = DocumentsForm(request.POST, use_required_attribute=False)
        form.fields["matter"].queryset = Matter.objects.filter(status="Open").order_by(
            "name"
        )

        uploaded_file = request.FILES.get("file")

        # Validate file is uploaded
        if not uploaded_file:
            form.add_error(None, "FILE_REQUIRED: Please select a file to upload.")

        if form.is_valid() and uploaded_file:
            document = form.save(commit=False)

            document.uploaded_by = request.user
            document.file = uploaded_file

            document.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "documentsChanged"})

        # Form has errors
        return render(request, "documents/form.html", {"form": form, "edit": False})

    else:
        form = DocumentsForm(use_required_attribute=False)
        form.fields["matter"].queryset = Matter.objects.filter(status="Open").order_by(
            "name"
        )

        # Pre-select matter if matter_id is provided
        if matter_id:
            try:
                matter = Matter.objects.get(id=matter_id)
                form.initial["matter"] = matter
            except Matter.DoesNotExist:
                pass

        return render(request, "documents/form.html", {"form": form, "edit": False})


@login_required
def documents_edit(request, document_id):
    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        return HttpResponse(status=404)

    matter_list = Matter.objects.filter(status="Open").order_by("name")

    if document.matter not in matter_list:
        matter_list |= Matter.objects.filter(pk=document.matter.id)

    if request.method == "POST":
        form = DocumentsForm(
            request.POST, instance=document, use_required_attribute=False
        )

        form.fields["matter"].queryset = matter_list

        uploaded_file = request.FILES.get("file")

        if not uploaded_file and not document.file:
            form.add_error(None, "FILE_REQUIRED: Please select a file to upload.")

        if form.is_valid():
            document = form.save(commit=False)

            document.uploaded_by = request.user
            if uploaded_file:
                document.file = uploaded_file

            document.save()

            return HttpResponse(
                status=204,
                headers={"HX-Trigger": "documentsChanged"},
            )

        # Form has errors
        return render(
            request,
            "documents/form.html",
            {"form": form, "document": document, "edit": True},
        )
    else:
        form = DocumentsForm(instance=document, use_required_attribute=False)

        form.fields["matter"].queryset = matter_list

        return render(
            request,
            "documents/form.html",
            {"form": form, "document": document, "edit": True},
        )


@login_required
def documents_delete(request, document_id):
    try:
        Document.objects.get(id=document_id).delete()
    except Document.DoesNotExist:
        return HttpResponse(status=404)

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
