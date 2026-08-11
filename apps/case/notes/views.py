from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

import apps.drive.google as drive_google
from apps.case.models import Document, Highlight
from apps.case.views import get_matter_from_url, get_session_key, set_last_tab
from apps.matters.models import Matter
from apps.notes.models import Note
from apps.notes.views import get_editor_file_tree, record_note_view

from .filters import NotesFilter
from .forms import NoteForm


def get_notes_data(request, matter, matter_id):
    """Get notes data with filters applied from session."""
    filter_session_key = get_session_key("notes_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    notes = []
    if matter:
        queryset = Note.objects.filter(matter=matter).order_by("-updated_at")

        if filter_data:
            notes_filter = NotesFilter(filter_data, queryset=queryset, matter=matter)
            notes = notes_filter.qs
        else:
            notes = queryset

    current_order = filter_data.get("order_by", "-updated_at")
    if isinstance(current_order, list):
        current_order = current_order[0] if current_order else "-updated_at"

    keyword = filter_data.get("keyword", "")
    if isinstance(keyword, list):
        keyword = keyword[0] if keyword else ""

    importance_value = filter_data.get("importance")
    importance_value = (
        int(importance_value) if importance_value not in (None, "", 0) else None
    )

    # Get category filter value
    category_key = filter_data.get("category", "")
    selected_category = ""
    if category_key:
        category_dict = dict(Note.CATEGORY_CHOICES)
        selected_category = category_dict.get(category_key, "")

    # Get selected topic
    selected_topic = filter_data.get("topic", "")

    # Get unique topics for dropdown
    topics = []
    if matter:
        topics = (
            Note.objects.filter(matter=matter)
            .exclude(topic__isnull=True)
            .exclude(topic="")
            .values_list("topic", flat=True)
            .distinct()
            .order_by("topic")
        )

    return {
        "notes": notes,
        "current_order": current_order,
        "keyword": keyword,
        "importances": list(range(7, 0, -1)),
        "importance_value": importance_value,
        "selected_importance": (
            {
                7: "Highest",
                6: "Higher",
                5: "High",
                4: "Normal",
                3: "Low",
                2: "Lower",
                1: "Lowest",
            }.get(importance_value, "")
            if importance_value
            else ""
        ),
        "category_choices": Note.CATEGORY_CHOICES,
        "selected_category": selected_category,
        "selected_category_key": category_key,
        "topics": topics,
        "selected_topic": selected_topic,
    }


@login_required
def notes_index(request, matter_id):
    """Main notes view."""
    matter, matters = get_matter_from_url(request, matter_id)
    set_last_tab(request, matter_id, "notes")

    context = {
        "app": "matters",
        "subapp": "notes",
        "matter": matter,
        "matters": matters,
    } | get_notes_data(request, matter, matter_id)

    return render(request, "case/notes/main.html", context)


@login_required
def notes_list(request, matter_id):
    """HTMX partial for notes list."""
    matter, matters = get_matter_from_url(request, matter_id)

    context = {
        "app": "matters",
        "subapp": "notes",
        "matter": matter,
        "matters": matters,
    } | get_notes_data(request, matter, matter_id)

    return render(request, "case/notes/list.html", context)


@login_required
def notes_add(request, matter_id):
    """Add a new note."""
    matter, matters = get_matter_from_url(request, matter_id)

    if request.method == "POST":
        form = NoteForm(request.POST, user=request.user, use_required_attribute=False)
        if form.is_valid():
            note = form.save(commit=False)
            note.author = request.user
            note.matter = matter
            note.save()

            # Open new note in a new browser tab
            note_url = reverse("case:note-view", args=[note.id])
            return HttpResponse(
                f'<script>window.open("{note_url}", "_blank");'
                "window.dispatchEvent(new CustomEvent('close-modal'));</script>",
                headers={"HX-Trigger": "notesChanged"},
            )
    else:
        form = NoteForm(
            initial={"matter": matter}, user=request.user, use_required_attribute=False
        )

    context = {
        "app": "matters",
        "subapp": "notes",
        "matter": matter,
        "form": form,
        "action": "Add",
    }

    return render(request, "case/notes/form.html", context)


@login_required
def note_view(request, note_id):
    """Standalone editor view for a note."""
    note = get_object_or_404(Note, pk=note_id)
    matter = note.matter

    # Record user's view of this note
    record_note_view(request.user, note)

    context = {"note": note, "matter": matter} | get_editor_file_tree(request, note)
    return render(request, "notes/editor.html", context)


@login_required
def note_content_partial(request, note_id):
    """HTMX partial for switching notes in the editor."""
    note = get_object_or_404(Note, pk=note_id)

    # Record user's view of this note
    record_note_view(request.user, note)

    context = {
        "note": note,
        "matter": note.matter,
    }
    return render(request, "notes/editor-content.html", context)


@login_required
def note_edit(request, note_id):
    """Edit note metadata (title, importance)."""
    note = get_object_or_404(Note, pk=note_id)
    matter = note.matter

    if request.method == "POST":
        form = NoteForm(
            request.POST, instance=note, user=request.user, use_required_attribute=False
        )
        if form.is_valid():
            form.save()
            return HttpResponse(status=204, headers={"HX-Trigger": "notesChanged"})
    else:
        form = NoteForm(instance=note, user=request.user, use_required_attribute=False)

    context = {
        "app": "matters",
        "subapp": "notes",
        "matter": matter,
        "note": note,
        "form": form,
        "action": "Edit",
    }

    return render(request, "case/notes/form.html", context)


@login_required
@require_POST
def note_delete(request, note_id):
    """Delete a note."""
    note = get_object_or_404(Note, pk=note_id)
    note.delete()

    return HttpResponse(status=204, headers={"HX-Trigger": "notesChanged"})


@login_required
def note_content(request, note_id):
    """GET returns markdown content, POST saves it."""
    note = get_object_or_404(Note, pk=note_id)

    if request.method == "POST":
        content = request.POST.get("content", "")
        note.content = content
        note.save()
        return HttpResponse(status=204)

    return HttpResponse(note.content, content_type="text/plain; charset=utf-8")


@login_required
@require_POST
def note_autosave(request, note_id):
    """Autosave endpoint for the editor."""
    note = get_object_or_404(Note, pk=note_id)

    content = request.POST.get("content", "")
    note.content = content
    # updated_by is set by AuditMixin.save; include it in update_fields so the
    # change is actually persisted.
    note.save(update_fields=["content", "updated_at", "updated_by"])

    return JsonResponse({"saved": True, "updated_at": note.updated_at.isoformat()})


@login_required
@require_POST
def note_title(request, note_id):
    """Update note title."""
    note = get_object_or_404(Note, pk=note_id)

    title = request.POST.get("title", "").strip()
    if title:
        note.title = title
        note.save(update_fields=["title", "updated_at", "updated_by"])
        return JsonResponse({"saved": True, "title": note.title})

    return JsonResponse({"saved": False, "error": "Title cannot be empty"}, status=400)


@login_required
def note_meta(request, note_id):
    """Render the note meta partial (used by HTMX to refresh after autosave)."""
    note = get_object_or_404(Note, pk=note_id)
    return render(request, "notes/meta.html", {"note": note})


@login_required
def notes_filter(request, matter_id):
    """Filter modal for notes."""
    matter, matters = get_matter_from_url(request, matter_id)
    filter_session_key = get_session_key("notes_filter", matter_id)

    if request.method == "POST":
        filter_data = {
            key: value
            for key, value in request.POST.items()
            if key != "csrfmiddlewaretoken"
        }
        request.session[filter_session_key] = filter_data
        request.session.modified = True
        return HttpResponse(status=204, headers={"HX-Trigger": "notesChanged"})

    filter_data = request.session.get(filter_session_key, {})
    queryset = Note.objects.filter(matter=matter) if matter else Note.objects.none()
    filter_obj = NotesFilter(filter_data, queryset=queryset, matter=matter)

    return render(
        request, "case/notes/filter.html", {"filter": filter_obj, "matter": matter}
    )


@login_required
def notes_sort(request, matter_id, order):
    """Sort notes by field."""
    filter_session_key = get_session_key("notes_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    current_order = filter_data.get("order_by", "")
    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session[filter_session_key] = filter_data
    request.session.modified = True

    return redirect("case:notes-list", matter_id=matter_id)


@login_required
def notes_filter_keyword(request, matter_id):
    """Filter notes by keyword."""
    matter, _ = get_matter_from_url(request, matter_id)
    filter_session_key = get_session_key("notes_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    keyword = request.GET.get("keyword", "").strip()

    if keyword:
        filter_data["keyword"] = keyword
    else:
        filter_data.pop("keyword", None)

    request.session[filter_session_key] = filter_data

    context = {"matter": matter} | get_notes_data(request, matter, matter_id)
    return render(request, "case/notes/table.html", context)


@login_required
def notes_filter_importance(request, matter_id, importance_value):
    """Filter notes by importance."""
    filter_session_key = get_session_key("notes_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    filter_data["importance"] = "" if importance_value == 0 else importance_value
    request.session[filter_session_key] = filter_data

    return redirect("case:notes-list", matter_id=matter_id)


@login_required
def notes_filter_category(request, matter_id, category):
    """Filter notes by category."""
    filter_session_key = get_session_key("notes_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    if category:
        filter_data["category"] = category
    else:
        filter_data.pop("category", None)

    request.session[filter_session_key] = filter_data

    return redirect("case:notes-list", matter_id=matter_id)


@login_required
def notes_filter_topic(request, matter_id, topic):
    """Filter notes by topic."""
    filter_session_key = get_session_key("notes_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    filter_data["topic"] = topic
    request.session[filter_session_key] = filter_data
    request.session.modified = True

    return redirect("case:notes-list", matter_id=matter_id)


@login_required
def notes_filter_topic_clear(request, matter_id):
    """Clear topic filter for notes."""
    filter_session_key = get_session_key("notes_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    filter_data.pop("topic", None)
    request.session[filter_session_key] = filter_data
    request.session.modified = True

    return redirect("case:notes-list", matter_id=matter_id)


@login_required
def notes_shortcuts(request, matter_id):
    """Show keyboard shortcuts modal."""
    return render(request, "notes/shortcuts-modal.html")


@login_required
def note_import_modal(request, note_id):
    """Show import markdown modal."""
    return render(request, "notes/import-modal.html")


@login_required
@require_POST
def note_category(request, note_id, value):
    """Update note category."""
    note = get_object_or_404(Note, pk=note_id)
    note.category = value
    note.save(update_fields=["category"])
    return redirect("case:notes-list", matter_id=note.matter_id)


@login_required
@require_POST
def note_importance(request, note_id, value):
    """Update note importance."""
    note = get_object_or_404(Note, pk=note_id)
    note.importance = value
    note.save(update_fields=["importance"])
    return redirect("case:notes-list", matter_id=note.matter_id)


@login_required
@require_POST
def note_set_ai(request, note_id, state):
    """Set the ai_context state on a note (auto/always/never).

    Editable for synced notes too — ai_context is app-only metadata that the
    Drive sync never overwrites.
    """
    if state not in ("auto", "always", "never"):
        return HttpResponse(status=400)

    note = get_object_or_404(Note, pk=note_id)
    note.ai_context = state
    note.save(update_fields=["ai_context", "updated_at", "updated_by"])

    return render(request, "case/notes/ai-context-cell.html", {"note": note})


@login_required
def reference_search(request, note_id):
    """Search documents and highlights for note references."""
    from django.db.models import Q

    note = get_object_or_404(Note, pk=note_id)
    matter = note.matter
    query = request.GET.get("q", "").strip()

    documents = []
    highlights = []

    if query and matter:
        # Search both documents and highlights
        documents = Document.objects.filter(matter=matter, name__icontains=query)[:15]
        highlights = (
            Highlight.objects.filter(document__matter=matter)
            .filter(Q(slug__icontains=query) | Q(text__icontains=query))
            .select_related("document")[:15]
        )

    context = {
        "note": note,
        "documents": documents,
        "highlights": highlights,
        "query": query,
    }
    return render(request, "notes/reference-results.html", context)


@login_required
def reference_citations(request, note_id):
    """Return current citations for references."""
    doc_ids = request.GET.getlist("doc")
    hl_ids = request.GET.getlist("hl")

    citations = {}

    for doc in Document.objects.filter(id__in=doc_ids):
        citations[f"doc:{doc.id}"] = doc.citation

    for hl in Highlight.objects.filter(id__in=hl_ids).select_related("document"):
        citations[f"hl:{hl.id}"] = hl.citation

    return JsonResponse(citations)


# ---------------------------------------------------------------------------
# Google Drive folder linking (Notes tab)
# ---------------------------------------------------------------------------


@login_required
def drive_link_modal(request, matter_id):
    """Modal to pick this matter's Google Drive folder from a live list."""
    matter, _ = get_matter_from_url(request, matter_id)

    folders = drive_google.list_matter_folders()
    # Folders already linked to a different matter (prevent mis-linking).
    taken = {
        m.drive_folder: m
        for m in Matter.objects.exclude(pk=matter.pk)
        .exclude(drive_folder__isnull=True)
        .exclude(drive_folder="")
    }
    folder_rows = [{"name": f, "taken_by": taken.get(f)} for f in folders]

    context = {
        "matter": matter,
        "folders": folder_rows,
        "current": matter.drive_folder,
        "linked": drive_google.check_credentials(),
    }
    return render(request, "case/notes/drive-link-modal.html", context)


@login_required
@require_POST
def drive_link(request, matter_id):
    """Set this matter's Drive folder and resync its notes immediately."""
    matter, _ = get_matter_from_url(request, matter_id)
    folder = request.POST.get("folder", "").strip()

    if folder:
        clash = Matter.objects.exclude(pk=matter.pk).filter(drive_folder=folder).first()
        if clash:
            # 200 so HTMX swaps the message into the modal's error slot.
            return HttpResponse(
                f'<p class="error-text">“{folder}” is already linked to '
                f"{clash}. Unlink it there first.</p>"
            )

    matter.drive_folder = folder or None
    matter.save(update_fields=["drive_folder"])
    # No note ingestion — the notes mirror is retired. The link only feeds
    # the record/key-document mirrors' matter resolution.

    return HttpResponse(status=204, headers={"HX-Refresh": "true"})


@login_required
@require_POST
def drive_unlink(request, matter_id):
    """Unlink this matter's Drive folder. Notes are app-owned and untouched."""
    matter, _ = get_matter_from_url(request, matter_id)
    matter.drive_folder = None
    matter.save(update_fields=["drive_folder"])

    return HttpResponse(status=204, headers={"HX-Refresh": "true"})
