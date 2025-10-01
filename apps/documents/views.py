from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render

from apps.documents.filters import DocumentsFilter, LabelsFilter
from apps.documents.forms import DocumentsForm, LabelsForm
from apps.documents.get_document_data import get_document_data
from apps.documents.get_label_data import get_label_data
from apps.documents.models import Document, Label, document_upload_path
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding


@login_required
def index(request):
    documents_data = get_document_data(request)

    context = {
        "app": "documents",
        "subapp": "documents",
    } | documents_data

    return render(request, "documents/documents/main.html", context)


@login_required
def documents_list(request):
    documents_data = get_document_data(request)

    context = {
        "app": "documents",
        "subapp": "documents",
    } | documents_data

    return render(request, "documents/documents/list.html", context)


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

        return render(request, "documents/documents/filter.html", {"filter": filter})


@login_required
def documents_filter_matter(request, matter_id):
    filter_data = request.session.get("documents_filter", {})
    filter_data["matter"] = matter_id

    request.session["documents_filter"] = filter_data

    return redirect("documents:list")


@login_required
def documents_filter_label(request, label_id):
    filter_data = request.session.get("documents_filter", {})
    filter_data["label"] = label_id

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
                form.fields["labels"].queryset = submitted_matter.labels.all()
            except Matter.DoesNotExist:
                form.fields["proceeding"].queryset = Proceeding.objects.none()
                form.fields["labels"].queryset = Label.objects.none()
        else:
            form.fields["proceeding"].queryset = Proceeding.objects.none()
            form.fields["labels"].queryset = Label.objects.none()

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
            form.save_m2m()

            return HttpResponse(status=204, headers={"HX-Trigger": "documentsChanged"})

        # Form has errors
        return render(
            request, "documents/documents/form.html", {"form": form, "edit": False}
        )

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

        return render(
            request, "documents/documents/form.html", {"form": form, "edit": False}
        )


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
                form.fields["labels"].queryset = submitted_matter.labels.all()
            except Matter.DoesNotExist:
                form.fields["proceeding"].queryset = Proceeding.objects.none()
                form.fields["labels"].queryset = Label.objects.none()
        else:
            form.fields["proceeding"].queryset = Proceeding.objects.none()
            form.fields["labels"].queryset = Label.objects.none()

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
            form.save_m2m()

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
            "documents/documents/form.html",
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
def get_proceedings_and_labels(request):
    matter_id = request.GET.get("matter")

    proceedings = []
    labels = []

    if matter_id:
        try:
            matter = Matter.objects.get(id=matter_id)

            proceedings = matter.proceeding_set.all().order_by("date_filed")
            labels = matter.labels.all().order_by("name")
        except Matter.DoesNotExist:
            pass

    proceedings_html = render(
        request,
        "documents/documents/proceeding_options.html",
        {"proceedings": proceedings},
    ).content.decode("utf-8")

    labels_html = render(
        request,
        "documents/documents/label_options.html",
        {"labels": labels},
    ).content.decode("utf-8")

    combined_html = f"""
        <select id="id_proceeding" hx-swap-oob="outerHTML" name="proceeding">
            {proceedings_html}
        </select>
        <select id="id_labels" hx-swap-oob="outerHTML" multiple class="span2" name="labels">
            {labels_html}
        </select>
    """

    return HttpResponse(combined_html)


@login_required
def labels_index(request):
    label_data = get_label_data(request)

    context = {
        "app": "documents",
        "subapp": "labels",
    } | label_data

    return render(request, "documents/labels/main.html", context)


@login_required
def labels_list(request):
    label_data = get_label_data(request)

    context = {
        "app": "documents",
        "subapp": "labels",
    } | label_data

    return render(request, "documents/labels/list.html", context)


@login_required
def add_label(request):
    if request.method == "POST":
        form = LabelsForm(request.POST, use_required_attribute=False)
        form.fields["matter"].queryset = Matter.objects.filter(status="Open").order_by(
            "name"
        )

        if form.is_valid():
            form.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "labelsChanged"})

        return render(
            request, "documents/labels/form.html", {"form": form, "edit": False}
        )
    else:
        form = LabelsForm(use_required_attribute=False)
        form.fields["matter"].queryset = Matter.objects.filter(status="Open").order_by(
            "name"
        )

        return render(
            request, "documents/labels/form.html", {"form": form, "edit": False}
        )


@login_required
def edit_label(request, label_id):
    try:
        label = Label.objects.get(id=label_id)
    except Label.DoesNotExist:
        return HttpResponse(status=404)

    matter_list = Matter.objects.filter(status="Open").order_by("name")

    if label.matter not in matter_list:
        matter_list |= Matter.objects.filter(pk=label.matter.id)

    if request.method == "POST":
        form = LabelsForm(request.POST, instance=label, use_required_attribute=False)

        form.fields["matter"].queryset = matter_list

        if form.is_valid():
            form.save()

            return HttpResponse(
                status=204,
                headers={"HX-Trigger": "labelsChanged"},
            )

        return render(
            request,
            "documents/labels/form.html",
            {"form": form, "label": label, "edit": True},
        )
    else:
        form = LabelsForm(instance=label, use_required_attribute=False)

        form.fields["matter"].queryset = matter_list

        return render(
            request,
            "documents/labels/form.html",
            {"form": form, "label": label, "edit": True},
        )


@login_required
def labels_filter(request):
    if request.method == "POST":
        request.session["labels_filter"] = request.POST

        return HttpResponse(status=204, headers={"HX-Trigger": "labelsChanged"})
    else:
        filter_data = request.session.get("labels_filter", {})

        if filter_data:
            filter = LabelsFilter(
                filter_data,
                queryset=Label.objects.all()
                .select_related("matter")
                .order_by("matter__name", "name"),
            )
        else:
            default_filter = {"order_by": "name"}

            filter = LabelsFilter(
                default_filter,
                queryset=Label.objects.all().select_related("matter").order_by("name"),
            )

        return render(request, "documents/labels/filter.html", {"filter": filter})


@login_required
def labels_sort(request, order):
    filter_data = request.session.get("labels_filter", {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["labels_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "labelsChanged"})


@login_required
def delete_label(request, label_id):
    try:
        Label.objects.get(id=label_id).delete()
    except Label.DoesNotExist:
        return HttpResponse(status=404)

    return HttpResponse(status=204, headers={"HX-Trigger": "labelsChanged"})


@login_required
def toggle_document_select(request, document_id):
    selected_documents = request.session.get("selected_documents", [])

    if document_id in selected_documents:
        selected_documents.remove(document_id)
    else:
        selected_documents.append(document_id)

    request.session["selected_documents"] = selected_documents

    return HttpResponse(status=204, headers={"HX-Trigger": "documentsChanged"})
