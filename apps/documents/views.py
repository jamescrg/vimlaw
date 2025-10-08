from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render

from apps.documents.filters import DocumentsFilter
from apps.documents.forms import DocumentsForm
from apps.documents.get_document_data import get_document_data
from apps.documents.models import Document, document_upload_path
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding


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

    # If matter_id is 0, redirect to the first available matter
    if matter_id == 0:
        matter_ids = Document.objects.values_list("matter_id", flat=True).distinct()
        first_matter = Matter.objects.filter(id__in=matter_ids).order_by("name").first()

        if first_matter:
            matter_id = first_matter.id

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

        submitted_matter_id = request.POST.get("matter")
        if submitted_matter_id:
            try:
                submitted_matter = Matter.objects.get(id=submitted_matter_id)
                form.fields["proceeding"].queryset = (
                    submitted_matter.proceeding_set.all()
                )
            except Matter.DoesNotExist:
                form.fields["proceeding"].queryset = Proceeding.objects.none()
        else:
            form.fields["proceeding"].queryset = Proceeding.objects.none()

        uploaded_file = request.FILES.get("file")

        # Validate file is uploaded
        if not uploaded_file:
            form.add_error(None, "FILE_REQUIRED: Please select a file to upload.")

        if form.is_valid() and uploaded_file:
            upload_path = document_upload_path(form.instance, uploaded_file.name)
            all_documents = Document.objects.all()

            if all_documents.filter(file=upload_path).exists():
                form.add_error(
                    "name", "A document with the same upload path already exists."
                )

                return render(
                    request, "documents/form.html", {"form": form, "edit": False}
                )

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

        filter_data = request.session.get("documents_filter", {})
        filter_matter_id = filter_data.get("matter")

        # Pre-select matter if ID is provided
        if matter_id:
            try:
                matter = Matter.objects.get(id=matter_id)
                form.initial["matter"] = matter
            except Matter.DoesNotExist:
                pass
        elif filter_matter_id and filter_matter_id != 0:
            try:
                matter = Matter.objects.get(id=filter_matter_id)
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

        submitted_matter_id = request.POST.get("matter")
        if submitted_matter_id:
            try:
                submitted_matter = Matter.objects.get(id=submitted_matter_id)
                form.fields["proceeding"].queryset = (
                    submitted_matter.proceeding_set.all()
                )
            except Matter.DoesNotExist:
                form.fields["proceeding"].queryset = Proceeding.objects.none()
        else:
            form.fields["proceeding"].queryset = Proceeding.objects.none()

        uploaded_file = request.FILES.get("file")

        if not uploaded_file and not document.file:
            form.add_error(None, "FILE_REQUIRED: Please select a file to upload.")

        if form.is_valid():
            document = form.save(commit=False)

            document.uploaded_by = request.user
            if uploaded_file:
                document.file = uploaded_file

            if uploaded_file:
                upload_path = document_upload_path(document, uploaded_file.name)
            else:
                upload_path = document_upload_path(document, document.file.name)

            print(f"Upload Path: {upload_path}")

            all_documents = Document.objects.exclude(id=document.id)

            if all_documents.filter(file=upload_path).exists():
                form.add_error(
                    "name", "A document with the same upload path already exists."
                )

                return render(
                    request,
                    "documents/form.html",
                    {"form": form, "document": document, "edit": True},
                )

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

    file_extension = document.file.name.split(".")[-1]
    full_file_name = f"{document.name}.{file_extension}"

    if document.category == "Record" and document.date:
        full_file_name = f"{document.date}_{full_file_name}"

    response["Content-Disposition"] = f'attachment; filename="{full_file_name}"'
    response["Content-Length"] = document.file.size

    return response


@login_required
def get_proceedings(request):
    matter_id = request.GET.get("matter")
    proceedings = []

    if matter_id:
        try:
            matter = Matter.objects.get(id=matter_id)
            proceedings = matter.proceeding_set.all().order_by("date_filed")
        except Matter.DoesNotExist:
            pass

    return render(
        request, "documents/proceeding_options.html", {"proceedings": proceedings}
    )
