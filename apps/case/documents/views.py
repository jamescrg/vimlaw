import json

from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.case.models import Document, Label
from apps.matters.models import Matter

from .filters import FilesFilter
from .forms import BulkFilesForm, FilesForm
from .get_document_data import get_document_data, get_selected_matter


@login_required
def index(request):
    documents_data = get_document_data(request)

    context = {
        "app": "documents",
        "subapp": "documents",
    } | documents_data

    return render(request, "case/documents/main.html", context)


@login_required
def documents_list(request):
    documents_data = get_document_data(request)

    context = {
        "app": "documents",
        "subapp": "documents",
    } | documents_data

    return render(request, "case/documents/list.html", context)


@login_required
def documents_filter(request):
    matter, matters = get_selected_matter(request)

    if request.method == "POST":
        # Convert QueryDict to regular dict, excluding CSRF token
        filter_data = {
            key: value
            for key, value in request.POST.items()
            if key != "csrfmiddlewaretoken"
        }
        request.session["documents_filter"] = filter_data

        return HttpResponse(status=204, headers={"HX-Trigger": "documentsChanged"})
    else:
        filter_data = request.session.get("documents_filter", {})

        # Build queryset filtered by matter
        queryset = (
            Document.objects.filter(matter=matter)
            .select_related("matter", "uploaded_by")
            .order_by("-uploaded_at")
            if matter
            else Document.objects.none()
        )

        filter_obj = FilesFilter(
            filter_data or {"order_by": "-uploaded_at"},
            queryset=queryset,
            matter=matter,
        )

        return render(request, "case/documents/filter.html", {"filter": filter_obj})


@login_required
def documents_filter_matter(request, matter_id):
    filter_data = request.session.get("documents_filter", {})
    filter_data["matter"] = matter_id

    request.session["documents_filter"] = filter_data

    return redirect("case:documents-list")


@login_required
def documents_filter_category(request, category=None):
    filter_data = request.session.get("documents_filter", {})
    if category:
        filter_data["category"] = category
    else:
        filter_data.pop("category", None)

    request.session["documents_filter"] = filter_data

    return redirect("case:documents-list")


@login_required
def documents_filter_keyword(request):
    filter_data = request.session.get("documents_filter", {})
    keyword = request.GET.get("keyword", "").strip()
    if keyword:
        filter_data["keyword"] = keyword
    else:
        filter_data.pop("keyword", None)

    request.session["documents_filter"] = filter_data

    # Render just the table partial (for search input updates)
    documents_data = get_document_data(request)
    return render(request, "case/documents/table.html", documents_data)


@login_required
def documents_filter_label(request, label_id):
    filter_data = request.session.get("documents_filter", {})
    filter_data["label"] = label_id

    request.session["documents_filter"] = filter_data

    return redirect("case:documents-list")


@login_required
def documents_filter_importance(request, importance_value):
    """Filter files by importance level."""
    filter_data = request.session.get("documents_filter", {})
    # Set to empty string when 0 (All) is selected, otherwise use the value
    filter_data["importance"] = "" if importance_value == 0 else importance_value

    request.session["documents_filter"] = filter_data

    return redirect("case:documents-list")


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

    return redirect("case:documents-list")


@login_required
def document_date(request, document_id):
    """Inline edit document date."""
    document = get_object_or_404(Document, id=document_id)

    if request.method == "POST":
        date_value = request.POST.get("date")
        if date_value:
            document.date = date_value
        else:
            document.date = None
        document.save()

        # Return the updated date display
        return render(
            request,
            "case/documents/date-display.html",
            {"document": document},
        )

    # GET - return the edit input
    return render(
        request,
        "case/documents/date-edit.html",
        {"document": document},
    )


@login_required
def document_category(request, document_id, category):
    """Set document category."""
    document = get_object_or_404(Document, id=document_id)
    document.category = category
    document.save()
    return redirect("case:documents-list")


@login_required
def document_proceeding(request, document_id, proceeding_id):
    """Set document proceeding."""
    from apps.matters.proceedings.models import Proceeding

    document = get_object_or_404(Document, id=document_id)

    if proceeding_id == 0:
        document.proceeding = None
    else:
        proceeding = get_object_or_404(Proceeding, id=proceeding_id)
        document.proceeding = proceeding

    document.save()
    return redirect("case:documents-list")


@login_required
def document_importance(request, document_id, importance):
    """Set document importance."""
    document = get_object_or_404(Document, id=document_id)
    document.importance = importance
    document.save()
    return redirect("case:documents-list")


@login_required
def documents_add(request, matter_id=None):
    # Get selected matter from session
    matter, matters = get_selected_matter(request)

    if not matter:
        return HttpResponse("No matter selected", status=400)

    if request.method == "POST":
        form = FilesForm(request.POST, matter=matter, use_required_attribute=False)
        uploaded_file = request.FILES.get("file")

        # Validate file is uploaded
        if not uploaded_file:
            form.add_error(None, "FILE_REQUIRED: Please select a file to upload.")

        if form.is_valid() and uploaded_file:
            # Two-phase save: first save without file to get PK
            document = form.save(commit=False)
            document.matter = matter
            document.uploaded_by = request.user
            document.save()  # Gets PK
            form.save_m2m()

            # Now save file with proper path using document.pk
            document.file = uploaded_file
            document.save()

            # Queue OCR for PDF files
            file_extension = uploaded_file.name.split(".")[-1].lower()
            if file_extension == "pdf":
                from django_q.tasks import async_task

                async_task(
                    "apps.case.tasks.process_document_ocr",
                    document.id,
                    task_name=f"OCR-{document.id}",
                    group="ocr_processing",
                )
            else:
                Document.objects.filter(id=document.id).update(
                    ocr_status="not_applicable"
                )

            return HttpResponse(status=204, headers={"HX-Trigger": "documentsChanged"})

        # Form has errors
        return render(
            request,
            "case/documents/form.html",
            {"form": form, "edit": False, "matter": matter},
        )

    else:
        form = FilesForm(matter=matter, use_required_attribute=False)

        return render(
            request,
            "case/documents/form.html",
            {"form": form, "edit": False, "matter": matter},
        )


@login_required
def documents_edit(request, document_id):
    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        return HttpResponse(status=404)

    # Use the document's matter for the form
    matter = document.matter
    old_matter_id = document.matter_id

    if request.method == "POST":
        form = FilesForm(
            request.POST, instance=document, matter=matter, use_required_attribute=False
        )

        uploaded_file = request.FILES.get("file")

        if not uploaded_file and not document.file:
            form.add_error(None, "FILE_REQUIRED: Please select a file to upload.")

        if form.is_valid():
            old_file_path = document.file.name if document.file else None

            document = form.save(commit=False)
            document.uploaded_by = request.user

            # If new file uploaded, delete old and reset OCR fields
            if uploaded_file:
                if old_file_path:
                    default_storage.delete(old_file_path)

                document.file = uploaded_file
                document.ocr_status = "pending"
                document.ocr_text = None
                document.ocr_error = None
                document.ocr_processed_at = None
                document.page_count = None
                document.ocr_pages_done = 0
            # If matter changed (and no new file), move file to new matter's folder
            elif document.matter_id != old_matter_id and old_file_path:
                file_extension = old_file_path.split(".")[-1].lower()
                new_file_path = (
                    f"case/{document.matter_id}/{document.pk}.{file_extension}"
                )

                # Read old file, save to new path, delete old
                with default_storage.open(old_file_path, "rb") as f:
                    file_content = f.read()
                default_storage.save(new_file_path, ContentFile(file_content))
                default_storage.delete(old_file_path)
                document.file.name = new_file_path

            document.save()
            form.save_m2m()

            # Queue OCR for new PDF file
            if uploaded_file:
                file_extension = uploaded_file.name.split(".")[-1].lower()
                if file_extension == "pdf":
                    from django_q.tasks import async_task

                    async_task(
                        "apps.case.tasks.process_document_ocr",
                        document.id,
                        task_name=f"OCR-{document.id}",
                        group="ocr_processing",
                    )
                else:
                    Document.objects.filter(id=document.id).update(
                        ocr_status="not_applicable"
                    )

            return HttpResponse(
                status=204,
                headers={"HX-Trigger": "documentsChanged"},
            )

        # Form has errors
        return render(
            request,
            "case/documents/form.html",
            {"form": form, "document": document, "edit": True, "matter": matter},
        )
    else:
        form = FilesForm(instance=document, matter=matter, use_required_attribute=False)

        return render(
            request,
            "case/documents/form.html",
            {"form": form, "document": document, "edit": True, "matter": matter},
        )


@login_required
def bulk_documents_update(request):
    matter, matters = get_selected_matter(request)
    selected_documents = request.session.get("selected_documents", [])

    if not selected_documents:
        return HttpResponse(status=400, content="No documents selected.")

    if request.method == "POST":
        form = BulkFilesForm(request.POST, matter=matter, use_required_attribute=False)

        if form.is_valid():
            proceeding = form.cleaned_data.get("proceeding")
            labels = form.cleaned_data.get("labels")

            documents = Document.objects.filter(id__in=selected_documents)

            for document in documents:
                if proceeding:
                    document.proceeding = proceeding
                if labels:
                    document.labels.set(labels)

                document.save()

            request.session["selected_documents"] = []

            return HttpResponse(
                status=204,
                headers={"HX-Trigger": "documentsChanged"},
            )

        return render(
            request,
            "case/documents/bulk_form.html",
            {"form": form, "matter": matter},
        )
    else:
        form = BulkFilesForm(matter=matter, use_required_attribute=False)

        return render(
            request,
            "case/documents/bulk_form.html",
            {"form": form, "matter": matter},
        )


@login_required
def documents_delete(request, document_id):
    try:
        Document.objects.get(id=document_id).delete()

        selected_documents = request.session.get("selected_documents", [])
        if document_id in selected_documents:
            selected_documents.remove(document_id)

            request.session["selected_documents"] = selected_documents
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
def serve_document(request, document_id):
    """Serve document inline for PDF viewer (avoids CORS issues with S3)."""
    document = get_object_or_404(Document, id=document_id)

    file_content = document.file.read()

    response = HttpResponse(file_content, content_type="application/pdf")
    response["Content-Length"] = len(file_content)
    response["Cache-Control"] = "private, max-age=3600"

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
            # Include global labels + matter-specific labels
            labels = Label.objects.filter(Q(matter=None) | Q(matter=matter)).order_by(
                "matter", "name"
            )
        except Matter.DoesNotExist:
            pass
    else:
        # No matter selected - show only global labels
        labels = Label.objects.filter(matter=None).order_by("name")

    proceedings_html = render(
        request,
        "case/documents/proceeding_options.html",
        {"proceedings": proceedings},
    ).content.decode("utf-8")

    labels_html = render(
        request,
        "case/documents/label_options.html",
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
def toggle_document_select(request, document_id):
    selected_documents = request.session.get("selected_documents", [])

    if document_id in selected_documents:
        selected_documents.remove(document_id)
    else:
        selected_documents.append(document_id)

    request.session["selected_documents"] = selected_documents

    return HttpResponse(status=204, headers={"HX-Trigger": "documentsChanged"})


@login_required
def clear_document_selection(request):
    request.session["selected_documents"] = []

    return HttpResponse(status=204, headers={"HX-Trigger": "documentsChanged"})


@login_required
def document_row(request, document_id):
    """Return a single file row (for HTMX polling of OCR status)."""
    document = get_object_or_404(Document, id=document_id)
    selected_documents = request.session.get("selected_documents", [])
    matter = document.matter
    proceedings = matter.proceeding_set.all().order_by("forum", "case_number")

    return render(
        request,
        "case/documents/row.html",
        {
            "document": document,
            "selected_documents": selected_documents,
            "proceedings": proceedings,
        },
    )


@login_required
def documents_edit_name(request, document_id):
    """Edit file name inline."""
    document = get_object_or_404(Document, id=document_id)

    if request.method == "POST":
        document.name = request.POST.get("name", document.name)
        document.save()

        selected_documents = request.session.get("selected_documents", [])
        proceedings = document.matter.proceeding_set.all().order_by(
            "forum", "case_number"
        )

        return render(
            request,
            "case/documents/row.html",
            {
                "document": document,
                "selected_documents": selected_documents,
                "proceedings": proceedings,
            },
        )

    # GET - return the input field
    return render(
        request,
        "case/documents/edit-name.html",
        {"document": document},
    )


@login_required
def ocr_badge(request, document_id):
    """Return OCR status badge (for HTMX polling)."""
    document = get_object_or_404(Document, id=document_id)

    return render(
        request,
        "case/documents/ocr-badge.html",
        {"document": document},
    )


# PDF Viewer and OCR Views


@login_required
def document_viewer(request, document_id):
    """PDF viewer page for a document."""

    document = get_object_or_404(Document, id=document_id)
    highlights = document.highlights.all().order_by("page_number", "created_at")

    # Get query params for initial navigation
    initial_page = request.GET.get("page", 1)
    initial_highlight = request.GET.get("highlight")

    try:
        initial_page = int(initial_page)
    except (TypeError, ValueError):
        initial_page = 1

    try:
        initial_highlight = int(initial_highlight) if initial_highlight else None
    except (TypeError, ValueError):
        initial_highlight = None

    # Serialize highlights for JavaScript
    highlights_json = json.dumps(
        [
            {
                "id": h.id,
                "slug": h.slug,
                "text": h.text,
                "page_number": h.page_number,
                "coordinates": h.coordinates,
                "color": h.color,
            }
            for h in highlights
        ]
    )

    context = {
        "document": document,
        "highlights": highlights,
        "highlights_json": highlights_json,
        "initial_page": initial_page,
        "initial_highlight": initial_highlight,
    }

    return render(request, "case/viewer.html", context)


@login_required
def ocr_status(request, document_id):
    """Return OCR status for polling."""
    document = get_object_or_404(Document, id=document_id)

    return JsonResponse(
        {
            "status": document.ocr_status,
            "error": document.ocr_error,
            "processed_at": (
                document.ocr_processed_at.isoformat()
                if document.ocr_processed_at
                else None
            ),
            "page_count": document.page_count,
        }
    )


@login_required
@require_POST
def retry_ocr(request, document_id):
    """Retry OCR for a failed document."""
    document = get_object_or_404(Document, id=document_id)

    if document.ocr_status not in ["failed", "pending"]:
        return JsonResponse(
            {"error": "OCR cannot be retried for this document"}, status=400
        )

    from django_q.tasks import async_task

    async_task(
        "apps.case.tasks.process_document_ocr",
        document.id,
        task_name=f"OCR-Retry-{document.id}",
        group="ocr_processing",
    )

    document.ocr_status = "pending"
    document.save(update_fields=["ocr_status"])

    return JsonResponse({"success": True, "status": "pending"})
