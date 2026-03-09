import json

from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.case.models import Document, Label
from apps.case.views import get_matter_from_url, set_last_tab
from apps.management.selection import (
    clear_selected_ids,
    get_selected_ids,
    get_session_key,
    select_all_ids,
    selection_response,
    toggle_id,
)

from .filters import FilesFilter
from .forms import BulkFilesForm, FilesForm
from .get_document_data import get_document_data


@login_required
def index(request, matter_id):
    documents_data = get_document_data(request, matter_id)
    set_last_tab(request, matter_id, "documents")

    context = {
        "app": "matters",
        "subapp": "documents",
    } | documents_data

    return render(request, "case/documents/main.html", context)


@login_required
def documents_list(request, matter_id):
    documents_data = get_document_data(request, matter_id)

    context = {
        "app": "matters",
        "subapp": "documents",
    } | documents_data

    return render(request, "case/documents/list.html", context)


@login_required
def documents_filter(request, matter_id):
    matter, matters = get_matter_from_url(request, matter_id)
    filter_session_key = get_session_key("documents_filter", matter_id)

    if request.method == "POST":
        # Convert QueryDict to regular dict, excluding CSRF token
        filter_data = {
            key: value
            for key, value in request.POST.items()
            if key != "csrfmiddlewaretoken"
        }
        request.session[filter_session_key] = filter_data

        return HttpResponse(status=204, headers={"HX-Trigger": "documentsChanged"})
    else:
        filter_data = request.session.get(filter_session_key, {})

        # Build queryset filtered by matter
        queryset = (
            Document.objects.filter(matter=matter)
            .select_related("matter", "created_by")
            .order_by("-created_at")
            if matter
            else Document.objects.none()
        )

        filter_obj = FilesFilter(
            filter_data or {"order_by": "-created_at"},
            queryset=queryset,
            matter=matter,
        )

        return render(
            request,
            "case/documents/filter.html",
            {"filter": filter_obj, "matter": matter},
        )


@login_required
def documents_filter_category(request, matter_id, category=None):
    filter_session_key = get_session_key("documents_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    if category:
        filter_data["category"] = category
    else:
        filter_data.pop("category", None)

    request.session[filter_session_key] = filter_data
    request.session.modified = True

    return redirect("case:documents-list", matter_id=matter_id)


@login_required
def documents_filter_proceeding(request, matter_id, proceeding_id=None):
    filter_session_key = get_session_key("documents_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    if proceeding_id:
        filter_data["proceeding"] = proceeding_id
    else:
        filter_data.pop("proceeding", None)

    request.session[filter_session_key] = filter_data
    request.session.modified = True

    return redirect("case:documents-list", matter_id=matter_id)


@login_required
def documents_filter_keyword(request, matter_id):
    filter_session_key = get_session_key("documents_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    keyword = request.GET.get("keyword", "").strip()
    if keyword:
        filter_data["keyword"] = keyword
    else:
        filter_data.pop("keyword", None)

    request.session[filter_session_key] = filter_data

    # Render just the table partial (for search input updates)
    documents_data = get_document_data(request, matter_id)
    return render(request, "case/documents/table.html", documents_data)


@login_required
def documents_filter_label(request, matter_id, label_id):
    filter_session_key = get_session_key("documents_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    filter_data["label"] = label_id

    request.session[filter_session_key] = filter_data

    return redirect("case:documents-list", matter_id=matter_id)


@login_required
def documents_filter_importance(request, matter_id, importance_value):
    """Filter files by importance level."""
    filter_session_key = get_session_key("documents_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    # Set to empty string when 0 (All) is selected, otherwise use the value
    filter_data["importance"] = "" if importance_value == 0 else importance_value

    request.session[filter_session_key] = filter_data

    return redirect("case:documents-list", matter_id=matter_id)


@login_required
def documents_sort(request, matter_id, order):
    filter_session_key = get_session_key("documents_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session[filter_session_key] = filter_data

    return redirect("case:documents-list", matter_id=matter_id)


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
    return redirect("case:documents-list", matter_id=document.matter_id)


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
    return redirect("case:documents-list", matter_id=document.matter_id)


@login_required
def document_importance(request, document_id, importance):
    """Set document importance."""
    document = get_object_or_404(Document, id=document_id)
    document.importance = importance
    document.save()
    return redirect("case:documents-list", matter_id=document.matter_id)


@login_required
def documents_add(request, matter_id):
    matter, matters = get_matter_from_url(request, matter_id)

    if request.method == "POST":
        form = FilesForm(request.POST, matter=matter, use_required_attribute=False)
        uploaded_file = request.FILES.get("file")

        # Validate file is uploaded and has valid extension
        if not uploaded_file:
            form.add_error(None, "FILE_REQUIRED: Please select a file to upload.")
        else:
            file_ext = uploaded_file.name.lower().split(".")[-1]
            if file_ext not in ("pdf", "mbox"):
                form.add_error(
                    None, "FILE_REQUIRED: Only PDF and mbox files are accepted."
                )

        if form.is_valid() and uploaded_file:
            file_ext = uploaded_file.name.lower().split(".")[-1]

            # Handle mbox files - convert to PDF
            if file_ext == "mbox":
                import os

                from .mbox import (
                    generate_email_description,
                    generate_email_pdf,
                    parse_mbox_file,
                )

                try:
                    # Parse the mbox file
                    file_content = uploaded_file.read()
                    email_metadata = parse_mbox_file(file_content)

                    # Generate PDF
                    base_url = request.build_absolute_uri("/").rstrip("/")
                    pdf_file = generate_email_pdf(email_metadata, base_url)

                    # Create document with auto-populated fields
                    document = form.save(commit=False)
                    document.matter = matter
                    document.created_by = request.user

                    # Auto-set date from email
                    if email_metadata.date:
                        document.date = email_metadata.date.date()

                    # Auto-set description
                    document.description = generate_email_description(email_metadata)

                    document.save()  # Gets PK
                    form.save_m2m()

                    # Read PDF content and save as file
                    with open(pdf_file.name, "rb") as f:
                        pdf_content = f.read()

                    # Clean up temp file
                    os.unlink(pdf_file.name)

                    # Save with .pdf extension
                    document.file.save(
                        f"{document.pk}.pdf", ContentFile(pdf_content), save=True
                    )

                    # Queue OCR for the generated PDF
                    from django_q.tasks import async_task

                    async_task(
                        "apps.case.documents.tasks.process_document_ocr",
                        document.id,
                        task_name=f"OCR-{document.id}",
                        group="ocr_processing",
                    )

                    return HttpResponse(
                        status=204, headers={"HX-Trigger": "documentsChanged"}
                    )

                except ValueError as e:
                    form.add_error(None, f"FILE_REQUIRED: {str(e)}")
                except Exception as e:
                    form.add_error(
                        None, f"FILE_REQUIRED: Failed to process email file: {str(e)}"
                    )

            # Handle regular PDF files
            elif file_ext == "pdf":
                # Two-phase save: first save without file to get PK
                document = form.save(commit=False)
                document.matter = matter
                document.created_by = request.user
                document.save()  # Gets PK
                form.save_m2m()

                # Now save file with proper path using document.pk
                document.file = uploaded_file
                document.save()

                # Queue OCR for PDF files
                from django_q.tasks import async_task

                async_task(
                    "apps.case.documents.tasks.process_document_ocr",
                    document.id,
                    task_name=f"OCR-{document.id}",
                    group="ocr_processing",
                )

                return HttpResponse(
                    status=204, headers={"HX-Trigger": "documentsChanged"}
                )

        # Form has errors
        return render(
            request,
            "case/documents/form.html",
            {"form": form, "edit": False, "matter": matter},
        )

    else:
        # Get selected category and proceeding from filter to pre-populate form
        filter_session_key = get_session_key("documents_filter", matter_id)
        filter_data = request.session.get(filter_session_key, {})
        selected_category = filter_data.get("category")
        selected_proceeding = filter_data.get("proceeding")

        form = FilesForm(
            matter=matter,
            initial_category=selected_category,
            initial_proceeding=selected_proceeding,
            use_required_attribute=False,
        )

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
        elif uploaded_file and not uploaded_file.name.lower().endswith(".pdf"):
            form.add_error(None, "FILE_REQUIRED: Only PDF files are accepted.")
            uploaded_file = None  # Prevent processing invalid file

        if form.is_valid():
            old_file_path = document.file.name if document.file else None

            document = form.save(commit=False)
            document.updated_by = request.user

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
                        "apps.case.documents.tasks.process_document_ocr",
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
def bulk_documents_update(request, matter_id):
    matter, matters = get_matter_from_url(request, matter_id)

    key = get_session_key("selected_documents", matter_id)
    selected_documents = get_selected_ids(request, key)

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

            clear_selected_ids(request, key)

            return selection_response("documentsChanged")

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
        document = Document.objects.get(id=document_id)
        matter_id = document.matter_id
        document.delete()

        # Clean up from selected documents
        key = get_session_key("selected_documents", matter_id)
        if document_id in get_selected_ids(request, key):
            toggle_id(request, key, document_id)
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
def get_proceedings_and_labels(request, matter_id):
    matter, matters = get_matter_from_url(request, matter_id)

    proceedings = matter.proceeding_set.all().order_by("date_filed")
    # Include global labels + matter-specific labels
    labels = Label.objects.filter(Q(matter=None) | Q(matter=matter)).order_by(
        "matter", "name"
    )

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
@require_POST
def toggle_document_select(request, matter_id, document_id):
    # Validate document exists and belongs to matter
    get_object_or_404(Document, id=document_id, matter_id=matter_id)
    key = get_session_key("selected_documents", matter_id)

    toggle_id(request, key, document_id)

    return selection_response("documentsChanged")


@login_required
def clear_document_selection(request, matter_id):
    clear_selected_ids(request, get_session_key("selected_documents", matter_id))

    return selection_response("documentsChanged")


@login_required
def document_row(request, document_id):
    """Return a single file row (for HTMX polling of OCR status)."""
    document = get_object_or_404(Document, id=document_id)
    matter_id = document.matter_id
    selected_documents = get_selected_ids(
        request, get_session_key("selected_documents", matter_id)
    )
    matter = document.matter
    proceedings = matter.proceeding_set.all().order_by("forum", "case_number")

    return render(
        request,
        "case/documents/row.html",
        {
            "document": document,
            "selected_documents": selected_documents,
            "proceedings": proceedings,
            "matter": matter,
        },
    )


@login_required
def documents_edit_name(request, document_id):
    """Edit file name inline."""
    document = get_object_or_404(Document, id=document_id)
    matter_id = document.matter_id

    if request.method == "POST":
        document.name = request.POST.get("name", document.name)
        document.save()

        selected_documents = get_selected_ids(
            request, get_session_key("selected_documents", matter_id)
        )
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
                "matter": document.matter,
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
    hide_on_bypass = request.GET.get("hide_on_bypass") == "1"

    return render(
        request,
        "case/documents/ocr-badge.html",
        {"document": document, "hide_on_bypass": hide_on_bypass},
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
        "matter": document.matter,
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
        "apps.case.documents.tasks.process_document_ocr",
        document.id,
        task_name=f"OCR-Retry-{document.id}",
        group="ocr_processing",
    )

    document.ocr_status = "pending"
    document.save(update_fields=["ocr_status"])

    return JsonResponse({"success": True, "status": "pending"})


@login_required
@require_POST
def accept_ocr(request, document_id):
    """Accept extracted text and mark OCR as completed."""
    document = get_object_or_404(Document, id=document_id)

    if document.ocr_status != "extracted":
        return HttpResponse(status=400)

    document.ocr_status = "completed"
    document.save(update_fields=["ocr_status"])

    # Return hidden span instead of empty response to prevent modal auto-close
    return HttpResponse('<span class="d-none"></span>')


@login_required
@require_POST
def force_ocr(request, document_id):
    """Force OCR on a document that was previously skipped."""
    document = get_object_or_404(Document, id=document_id)

    if document.ocr_status != "extracted":
        return HttpResponse(status=400)

    from django_q.tasks import async_task

    async_task(
        "apps.case.documents.tasks.process_document_ocr",
        document.id,
        True,  # force=True
        task_name=f"OCR-Force-{document.id}",
        group="ocr_processing",
    )

    document.ocr_status = "pending"
    document.save(update_fields=["ocr_status"])

    # Return the badge HTML showing pending status
    return render(
        request,
        "case/documents/ocr-badge.html",
        {"document": document},
    )


@login_required
@require_POST
def documents_toggle_ai(request, document_id):
    """Toggle the include_in_ai flag on a document."""
    document = get_object_or_404(Document, pk=document_id)

    document.include_in_ai = not document.include_in_ai
    document.save(update_fields=["include_in_ai", "updated_by", "updated_at"])

    return HttpResponse(status=204)


@login_required
@require_POST
def select_all_documents(request, matter_id):
    """Toggle select-all for documents."""
    key = get_session_key("selected_documents", matter_id)

    visible_ids = [doc.id for doc in get_document_data(request, matter_id)["objects"]]
    select_all_ids(request, key, visible_ids)

    return selection_response("documentsChanged")


@login_required
@require_POST
def bulk_documents_ai(request, matter_id, action):
    """Bulk add/remove documents from AI context."""
    key = get_session_key("selected_documents", matter_id)
    selected_documents = get_selected_ids(request, key)

    if not selected_documents:
        return HttpResponse(status=400, content="No documents selected.")

    Document.objects.filter(id__in=selected_documents).update(
        include_in_ai=action == "add"
    )

    clear_selected_ids(request, key)
    return selection_response("documentsChanged")


@login_required
@require_POST
def bulk_documents_delete(request, matter_id):
    """Bulk delete selected documents."""
    key = get_session_key("selected_documents", matter_id)
    selected_documents = get_selected_ids(request, key)

    if not selected_documents:
        return HttpResponse(status=400, content="No documents selected.")

    Document.objects.filter(id__in=selected_documents).delete()
    clear_selected_ids(request, key)

    return selection_response("documentsChanged")


@login_required
def bulk_documents_category(request, matter_id):
    """Show modal to select category for bulk move."""
    matter, _ = get_matter_from_url(request, matter_id)
    key = get_session_key("selected_documents", matter_id)
    selected_documents = get_selected_ids(request, key)

    if request.method == "POST":
        category = request.POST.get("category")
        if category:
            Document.objects.filter(id__in=selected_documents).update(category=category)
            clear_selected_ids(request, key)
            return selection_response("documentsChanged")

        return HttpResponse(status=400, content="No category selected.")

    # GET - render modal
    categories = [
        ("Correspondence", "Correspondence"),
        ("Discovery", "Discovery"),
        ("Evidence", "Evidence"),
        ("Record", "Record"),
    ]

    return render(
        request,
        "case/documents/bulk_category_modal.html",
        {
            "matter": matter,
            "categories": categories,
            "selected_count": len(selected_documents),
        },
    )


@login_required
def bulk_documents_matter(request, matter_id):
    """Show modal to select matter for bulk move."""
    from apps.matters.models import Matter

    matter, matters = get_matter_from_url(request, matter_id)
    key = get_session_key("selected_documents", matter_id)
    selected_documents = get_selected_ids(request, key)

    if request.method == "POST":
        target_matter_id = request.POST.get("matter")

        if target_matter_id:
            target_matter = get_object_or_404(Matter, id=target_matter_id)

            # Move documents to new matter
            for doc in Document.objects.filter(id__in=selected_documents):
                old_file_path = doc.file.name if doc.file else None

                doc.matter = target_matter
                doc.save()

                # Move file to new matter's folder if file exists
                if old_file_path:
                    from django.core.files.base import ContentFile
                    from django.core.files.storage import default_storage

                    file_extension = old_file_path.split(".")[-1].lower()
                    new_file_path = f"case/{target_matter.id}/{doc.pk}.{file_extension}"

                    try:
                        with default_storage.open(old_file_path, "rb") as f:
                            file_content = f.read()
                        default_storage.save(new_file_path, ContentFile(file_content))
                        default_storage.delete(old_file_path)
                        doc.file.name = new_file_path
                        doc.save(update_fields=["file"])
                    except Exception:
                        pass  # File move failed, but document is still moved

            clear_selected_ids(request, key)
            return selection_response("documentsChanged")

        return HttpResponse(status=400, content="No matter selected.")

    # GET - render modal
    # Get all matters user has access to, excluding current
    available_matters = matters.exclude(id=matter_id).order_by("name")

    return render(
        request,
        "case/documents/bulk_matter_modal.html",
        {
            "matter": matter,
            "available_matters": available_matters,
            "selected_count": len(selected_documents),
        },
    )
