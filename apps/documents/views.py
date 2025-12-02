import json

from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.documents.filters import (
    DocumentsFilter,
    HighlightsFilter,
    LabelsFilter,
    TimelineFilter,
)
from apps.documents.forms import (
    BulkDocumentsForm,
    DocumentsForm,
    FactForm,
    HighlightForm,
    LabelsForm,
)
from apps.documents.generate_pdf import generate_timeline_pdf
from apps.documents.get_document_data import get_document_data, get_selected_matter
from apps.documents.get_label_data import get_label_data
from apps.documents.models import Document, Fact, Highlight, Label
from apps.matters.models import Matter


@login_required
def index(request):
    documents_data = get_document_data(request)

    context = {
        "app": "documents",
        "subapp": "documents",
    } | documents_data

    return render(request, "documents/documents/main.html", context)


@login_required
def select_matter(request, matter_id):
    """Change the selected matter for the documents app."""
    matter = get_object_or_404(Matter, pk=matter_id)
    request.session["documents_selected_matter"] = matter.id
    # Clear any existing filters when changing matter
    request.session.pop("documents_filter", None)
    request.session.pop("selected_documents", None)
    return redirect("documents:index")


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

        filter_obj = DocumentsFilter(
            filter_data or {"order_by": "-uploaded_at"},
            queryset=queryset,
            matter=matter,
        )

        return render(
            request, "documents/documents/filter.html", {"filter": filter_obj}
        )


@login_required
def documents_filter_matter(request, matter_id):
    filter_data = request.session.get("documents_filter", {})
    filter_data["matter"] = matter_id

    request.session["documents_filter"] = filter_data

    return redirect("documents:list")


@login_required
def documents_filter_category(request, category=None):
    filter_data = request.session.get("documents_filter", {})
    if category:
        filter_data["category"] = category
    else:
        filter_data.pop("category", None)

    request.session["documents_filter"] = filter_data

    return redirect("documents:list")


@login_required
def documents_filter_keyword(request):
    filter_data = request.session.get("documents_filter", {})
    keyword = request.GET.get("keyword", "").strip()
    if keyword:
        filter_data["keyword"] = keyword
    else:
        filter_data.pop("keyword", None)

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

    return redirect("documents:list")


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
            "documents/documents/date-display.html",
            {"document": document},
        )

    # GET - return the edit input
    return render(
        request,
        "documents/documents/date-edit.html",
        {"document": document},
    )


@login_required
def document_category(request, document_id, category):
    """Set document category."""
    document = get_object_or_404(Document, id=document_id)
    document.category = category
    document.save()
    return redirect("documents:list")


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
    return redirect("documents:list")


@login_required
def documents_add(request, matter_id=None):
    # Get selected matter from session
    matter, matters = get_selected_matter(request)

    if not matter:
        return HttpResponse("No matter selected", status=400)

    if request.method == "POST":
        form = DocumentsForm(request.POST, matter=matter, use_required_attribute=False)
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
                    "apps.documents.tasks.process_document_ocr",
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
            "documents/documents/form.html",
            {"form": form, "edit": False, "matter": matter},
        )

    else:
        form = DocumentsForm(matter=matter, use_required_attribute=False)

        return render(
            request,
            "documents/documents/form.html",
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
        form = DocumentsForm(
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
                    f"documents/{document.matter_id}/{document.pk}.{file_extension}"
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
                        "apps.documents.tasks.process_document_ocr",
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
            "documents/documents/form.html",
            {"form": form, "document": document, "edit": True, "matter": matter},
        )
    else:
        form = DocumentsForm(
            instance=document, matter=matter, use_required_attribute=False
        )

        return render(
            request,
            "documents/documents/form.html",
            {"form": form, "document": document, "edit": True, "matter": matter},
        )


@login_required
def bulk_document_update(request):
    matter, matters = get_selected_matter(request)
    selected_documents = request.session.get("selected_documents", [])

    if not selected_documents:
        return HttpResponse(status=400, content="No documents selected.")

    if request.method == "POST":
        form = BulkDocumentsForm(
            request.POST, matter=matter, use_required_attribute=False
        )

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
            "documents/documents/bulk_form.html",
            {"form": form, "matter": matter},
        )
    else:
        form = BulkDocumentsForm(matter=matter, use_required_attribute=False)

        return render(
            request,
            "documents/documents/bulk_form.html",
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


@login_required
def clear_document_selection(request):
    request.session["selected_documents"] = []

    return HttpResponse(status=204, headers={"HX-Trigger": "documentsChanged"})


@login_required
def document_row(request, document_id):
    """Return a single document row (for HTMX polling of OCR status)."""
    document = get_object_or_404(Document, id=document_id)
    selected_documents = request.session.get("selected_documents", [])
    matter = document.matter
    proceedings = matter.proceeding_set.all().order_by("forum", "case_number")

    return render(
        request,
        "documents/documents/row.html",
        {
            "document": document,
            "selected_documents": selected_documents,
            "proceedings": proceedings,
        },
    )


@login_required
def ocr_badge(request, document_id):
    """Return OCR status badge (for HTMX polling)."""
    document = get_object_or_404(Document, id=document_id)

    return render(
        request,
        "documents/documents/ocr-badge.html",
        {"document": document},
    )


# PDF Viewer and Highlighting Views


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

    return render(request, "documents/viewer.html", context)


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
def add_highlight(request, document_id):
    """Create a new highlight."""
    document = get_object_or_404(Document, id=document_id)

    try:
        coordinates = json.loads(request.POST.get("coordinates", "{}"))

        highlight = Highlight.objects.create(
            document=document,
            slug=request.POST.get("slug"),
            text=request.POST.get("text"),
            page_number=int(request.POST.get("page_number")),
            coordinates=coordinates,
            color=request.POST.get("color", "yellow"),
            created_by=request.user,
        )

        return JsonResponse(
            {
                "id": highlight.id,
                "slug": highlight.slug,
                "text": highlight.text,
                "page_number": highlight.page_number,
                "coordinates": highlight.coordinates,
                "color": highlight.color,
            }
        )
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
def delete_highlight(request, highlight_id):
    """Delete a highlight."""
    highlight = get_object_or_404(Highlight, id=highlight_id)

    # Check permission (creator or allow all authenticated users for now)
    highlight.delete()

    # Return empty response for HTMX (removes the row), JSON for JS
    if request.headers.get("HX-Request"):
        return HttpResponse("")
    return JsonResponse({"success": True})


@login_required
def edit_highlight(request, highlight_id):
    """Edit a highlight's slug, color, and importance."""
    highlight = get_object_or_404(Highlight, id=highlight_id)

    if request.method == "POST":
        form = HighlightForm(request.POST, instance=highlight)
        if form.is_valid():
            form.save()
            return render(
                request,
                "documents/highlights/row.html",
                {"highlight": highlight},
            )
    else:
        form = HighlightForm(instance=highlight)

    return render(
        request,
        "documents/highlights/edit.html",
        {"highlight": highlight, "form": form},
    )


@login_required
def highlight_link(request, highlight_id):
    """Redirect to viewer at specific highlight location."""
    highlight = get_object_or_404(Highlight, id=highlight_id)

    from django.urls import reverse

    viewer_url = reverse("documents:viewer", args=[highlight.document_id])
    return redirect(
        f"{viewer_url}?page={highlight.page_number}&highlight={highlight.id}"
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
        "apps.documents.tasks.process_document_ocr",
        document.id,
        task_name=f"OCR-Retry-{document.id}",
        group="ocr_processing",
    )

    document.ocr_status = "pending"
    document.save(update_fields=["ocr_status"])

    return JsonResponse({"success": True, "status": "pending"})


# =============================================================================
# Highlights Subapp
# =============================================================================


def get_highlights_data(request, matter):
    """Get highlights data with filters applied from session."""
    filter_data = request.session.get("highlights_filter", {})

    highlights = []
    documents = []
    selected_document = None

    # Extract values from filter_data (handles both list and string formats)
    def get_filter_value(key):
        val = filter_data.get(key, "")
        return val[0] if isinstance(val, list) else val

    keyword = get_filter_value("keyword")
    order_by = get_filter_value("order_by")
    document_id = get_filter_value("document")

    if matter:
        highlights = Highlight.objects.filter(document__matter=matter).select_related(
            "document", "document__matter", "created_by"
        )
        documents = Document.objects.filter(matter=matter).order_by("name")

        # Apply filters using HighlightsFilter
        highlight_filter = HighlightsFilter(
            filter_data, queryset=highlights, matter=matter
        )
        highlights = highlight_filter.qs

        # Get selected document for template
        if document_id:
            selected_document = documents.filter(id=document_id).first()

        # Handle custom ordering with secondary sorts
        if order_by == "document":
            highlights = highlights.order_by("document__name", "slug", "page_number")
        elif order_by == "-document":
            highlights = highlights.order_by("-document__name", "slug", "page_number")
        elif order_by == "slug":
            highlights = highlights.order_by("slug", "document__name", "page_number")
        elif order_by == "-slug":
            highlights = highlights.order_by("-slug", "document__name", "page_number")
        elif not order_by:
            # Default: order by document, then slug
            highlights = highlights.order_by("document__name", "slug", "page_number")

    # Determine current_order for template (strip leading '-' for base field)
    current_order = order_by if order_by else "document"

    return {
        "highlights": highlights,
        "documents": documents,
        "selected_document": selected_document,
        "keyword": keyword,
        "order_by": order_by,
        "current_order": current_order,
    }


@login_required
def highlights_index(request):
    """Main highlights list view."""
    matter, matters = get_selected_matter(request)

    context = {
        "app": "documents",
        "subapp": "highlights",
        "matter": matter,
        "matters": matters,
    } | get_highlights_data(request, matter)

    return render(request, "documents/highlights/main.html", context)


@login_required
def highlights_list(request):
    """HTMX partial for highlights list."""
    matter, matters = get_selected_matter(request)

    context = {
        "app": "documents",
        "subapp": "highlights",
        "matter": matter,
        "matters": matters,
    } | get_highlights_data(request, matter)

    return render(request, "documents/highlights/list.html", context)


@login_required
def highlights_filter_document(request, document_id=None):
    """Filter highlights by document (inline dropdown)."""
    filter_data = request.session.get("highlights_filter", {})

    if document_id:
        filter_data["document"] = document_id  # Store as int
    else:
        filter_data["document"] = ""  # Empty string for "All"

    request.session["highlights_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "highlightsChanged"})


@login_required
def highlights_for_document(request, document_id):
    """Set document filter and redirect to highlights page."""
    filter_data = request.session.get("highlights_filter", {})
    filter_data["document"] = document_id
    request.session["highlights_filter"] = filter_data

    return redirect("documents:highlights-index")


@login_required
def highlights_filter_keyword(request):
    """Filter highlights by keyword (inline search)."""
    filter_data = request.session.get("highlights_filter", {})
    keyword = request.POST.get("keyword", "").strip()

    filter_data["keyword"] = keyword  # Store as simple string

    request.session["highlights_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "highlightsChanged"})


@login_required
def highlights_filter(request):
    """Filter modal for highlights - GET shows modal, POST saves to session."""
    matter, matters = get_selected_matter(request)

    if request.method == "POST":
        # Store POST values directly (matching tasks pattern)
        filter_data = {
            key: value
            for key, value in request.POST.items()
            if key != "csrfmiddlewaretoken"
        }
        request.session["highlights_filter"] = filter_data
        return HttpResponse(status=204, headers={"HX-Trigger": "highlightsChanged"})

    # GET - show filter modal
    filter_data = request.session.get("highlights_filter", {})

    queryset = (
        Highlight.objects.filter(document__matter=matter)
        if matter
        else Highlight.objects.none()
    )

    filter_obj = HighlightsFilter(filter_data, queryset=queryset, matter=matter)

    context = {
        "filter": filter_obj,
    }

    return render(request, "documents/highlights/filter.html", context)


@login_required
def highlights_filter_sort(request, order):
    """Sort highlights by field, toggling asc/desc."""
    filter_data = request.session.get("highlights_filter", {})
    current_order = filter_data.get("order_by", "")

    # Toggle direction if same field
    if current_order == order:
        filter_data["order_by"] = f"-{order}"
    elif current_order == f"-{order}":
        filter_data["order_by"] = order
    else:
        filter_data["order_by"] = order

    request.session["highlights_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "highlightsChanged"})


@login_required
def highlights_filter_default(request):
    """Reset highlights filter to defaults."""
    request.session["highlights_filter"] = {
        "document": "",
        "keyword": "",
        "order_by": "document",
    }
    return redirect("documents:highlights-index")


# =============================================================================
# Timeline Subapp (Facts)
# =============================================================================


@login_required
def timeline_index(request):
    """Main timeline view."""
    matter, matters = get_selected_matter(request)

    facts = []
    if matter:
        facts = Fact.objects.filter(matter=matter).order_by("date", "time")

    context = {
        "app": "documents",
        "subapp": "timeline",
        "matter": matter,
        "matters": matters,
        "facts": facts,
    }

    return render(request, "documents/timeline/main.html", context)


@login_required
def timeline_list(request):
    """HTMX partial for timeline list."""
    matter, matters = get_selected_matter(request)

    facts = []
    if matter:
        facts = Fact.objects.filter(matter=matter).order_by("date", "time")
        # Apply filters
        timeline_filter = TimelineFilter(request.GET, queryset=facts)
        facts = timeline_filter.qs

    context = {
        "app": "documents",
        "subapp": "timeline",
        "matter": matter,
        "matters": matters,
        "facts": facts,
    }

    return render(request, "documents/timeline/list.html", context)


@login_required
def timeline_add(request):
    """Add a new timeline fact."""
    matter, matters = get_selected_matter(request)

    if not matter:
        return HttpResponse("No matter selected", status=400)

    if request.method == "POST":
        form = FactForm(request.POST, use_required_attribute=False)
        if form.is_valid():
            fact = form.save(commit=False)
            fact.user = request.user
            fact.matter = matter
            fact.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "timelineChanged"})
    else:
        form = FactForm(use_required_attribute=False)

    context = {
        "app": "documents",
        "subapp": "timeline",
        "matter": matter,
        "form": form,
        "action": "Add",
    }

    return render(request, "documents/timeline/form.html", context)


@login_required
def timeline_edit(request, fact_id):
    """Edit a timeline fact."""
    matter, matters = get_selected_matter(request)
    fact = get_object_or_404(Fact, pk=fact_id)

    if request.method == "POST":
        form = FactForm(request.POST, instance=fact, use_required_attribute=False)
        if form.is_valid():
            fact = form.save(commit=False)
            fact.user = request.user
            fact.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "timelineChanged"})
    else:
        form = FactForm(instance=fact, use_required_attribute=False)

    context = {
        "app": "documents",
        "subapp": "timeline",
        "matter": matter,
        "fact": fact,
        "form": form,
        "action": "Edit",
    }

    return render(request, "documents/timeline/form.html", context)


@login_required
@require_POST
def timeline_delete(request, fact_id):
    """Delete a timeline fact."""
    fact = get_object_or_404(Fact, pk=fact_id)
    fact.delete()

    return HttpResponse(status=204, headers={"HX-Trigger": "timelineChanged"})


@login_required
def timeline_print(request):
    """Print view for timeline."""
    matter, matters = get_selected_matter(request)

    facts = []
    if matter:
        facts = Fact.objects.filter(matter=matter).order_by("date", "time")

    context = {
        "matter": matter,
        "facts": facts,
    }
    return render(request, "documents/timeline/print.html", context)


@login_required
def timeline_pdf(request):
    """Generate PDF for timeline."""
    import os
    from datetime import datetime

    matter, matters = get_selected_matter(request)

    if not matter:
        return HttpResponse("No matter selected", status=400)

    file = generate_timeline_pdf(matter.id, request)

    current_date = datetime.now().strftime("%Y-%m-%d")

    with open(file.name, "rb") as pdf:
        response = HttpResponse(pdf.read(), content_type="application/pdf")
        filename = f'filename="Timeline - {matter.name} - {current_date}.pdf"'
        response["Content-Disposition"] = f"attachment; {filename}"

    os.unlink(file.name)

    return response


@login_required
def timeline_edit_description(request, fact_id):
    """Inline edit fact description."""
    matter, matters = get_selected_matter(request)
    fact = get_object_or_404(Fact, pk=fact_id)
    context = {"fact": fact, "matter": matter}
    return render(request, "documents/timeline/edit-description.html", context)


@login_required
def timeline_update_description(request, fact_id):
    """Update fact description inline."""
    matter, matters = get_selected_matter(request)
    fact = get_object_or_404(Fact, pk=fact_id)
    fact.description = request.POST.get("description")
    fact.save()

    context = {
        "matter": matter,
        "fact": fact,
    }
    return render(request, "documents/timeline/fact-row.html", context)


@login_required
def fact_sources_modal(request, fact_id):
    """Render modal for managing fact sources (documents and highlights)."""
    matter, matters = get_selected_matter(request)
    fact = get_object_or_404(Fact, pk=fact_id)
    context = {
        "fact": fact,
        "matter": matter,
    }
    return render(request, "documents/timeline/sources-modal.html", context)


@login_required
def fact_sources_search(request, fact_id):
    """Search documents and highlights for fact sources."""
    matter, matters = get_selected_matter(request)
    fact = get_object_or_404(Fact, pk=fact_id)
    query = request.GET.get("q", "").strip()

    documents = []
    highlights = []

    if query and matter:
        # Search documents by name
        documents = Document.objects.filter(matter=matter, name__icontains=query)[:10]

        # Search highlights by slug or text
        from django.db.models import Q

        highlights = (
            Highlight.objects.filter(document__matter=matter)
            .filter(Q(slug__icontains=query) | Q(text__icontains=query))
            .select_related("document")[:10]
        )

    context = {
        "fact": fact,
        "documents": documents,
        "highlights": highlights,
        "query": query,
    }
    return render(request, "documents/timeline/sources-results.html", context)


@login_required
@require_POST
def fact_add_source(request, fact_id):
    """Add a document or highlight as a source to a fact."""
    matter, matters = get_selected_matter(request)
    fact = get_object_or_404(Fact, pk=fact_id)

    source_type = request.POST.get("type")
    source_id = request.POST.get("id")

    if source_type == "document":
        document = get_object_or_404(Document, pk=source_id)
        fact.documents.add(document)
    elif source_type == "highlight":
        highlight = get_object_or_404(Highlight, pk=source_id)
        fact.highlights.add(highlight)

    context = {
        "matter": matter,
        "fact": fact,
    }
    return render(request, "documents/timeline/fact-row.html", context)


@login_required
@require_POST
def fact_remove_source(request, fact_id):
    """Remove a document or highlight source from a fact."""
    matter, matters = get_selected_matter(request)
    fact = get_object_or_404(Fact, pk=fact_id)

    source_type = request.POST.get("type")
    source_id = request.POST.get("id")

    if source_type == "document":
        document = get_object_or_404(Document, pk=source_id)
        fact.documents.remove(document)
    elif source_type == "highlight":
        highlight = get_object_or_404(Highlight, pk=source_id)
        fact.highlights.remove(highlight)

    context = {
        "matter": matter,
        "fact": fact,
    }
    return render(request, "documents/timeline/fact-row.html", context)
