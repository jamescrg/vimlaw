from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.management.pagination import CustomPaginator

from .filters import NotesFilter
from .forms import NoteForm
from .models import Note

SIDEBAR_SORT_OPTIONS = [
    ("-updated_at", "Modified, new to old"),
    ("-created_at", "Created, new to old"),
    ("title", "Title (A-Z)"),
]


def get_notes_data(request):
    """Get standalone notes data with filters applied from session."""
    filter_session_key = "standalone_notes_filter"
    filter_data = request.session.get(filter_session_key, {})

    queryset = Note.objects.filter(matter__isnull=True).order_by("-updated_at")

    if filter_data:
        notes_filter = NotesFilter(filter_data, queryset=queryset)
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

    category_key = filter_data.get("category", "")
    selected_category = ""
    if category_key:
        category_dict = dict(Note.CATEGORY_CHOICES)
        selected_category = category_dict.get(category_key, "")

    # Get selected topic
    selected_topic = filter_data.get("topic", "")

    # Get unique topics for dropdown
    topics = (
        Note.objects.filter(matter__isnull=True)
        .exclude(topic__isnull=True)
        .exclude(topic="")
        .values_list("topic", flat=True)
        .distinct()
        .order_by("topic")
    )

    # Pagination
    notes_list = list(notes)
    pagination = CustomPaginator(
        notes_list, per_page=20, request=request, session_key="standalone_notes_page"
    )

    return {
        "notes": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "standalone_notes_page",
        "trigger_key": "notesChanged",
        "number_notes": len(notes_list),
        "current_order": current_order.lstrip("-"),
        "keyword": keyword,
        "importances": list(range(1, 11)),
        "importance_value": importance_value,
        "selected_importance": (
            f"Importance {importance_value}" if importance_value else ""
        ),
        "category_choices": Note.CATEGORY_CHOICES,
        "selected_category": selected_category,
        "selected_category_key": category_key,
        "topics": topics,
        "selected_topic": selected_topic,
    }


@login_required
def notes_index(request):
    """Main standalone notes list view."""
    context = {
        "app": "notes",
    } | get_notes_data(request)

    return render(request, "notes/main.html", context)


@login_required
def notes_list(request):
    """HTMX partial for standalone notes list."""
    context = {
        "app": "notes",
    } | get_notes_data(request)

    return render(request, "notes/list.html", context)


@login_required
def notes_add(request):
    """Add a new standalone note."""
    if request.method == "POST":
        form = NoteForm(request.POST, use_required_attribute=False)
        if form.is_valid():
            note = form.save(commit=False)
            note.author = request.user
            note.matter = None
            note.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "notesChanged"})
    else:
        form = NoteForm(use_required_attribute=False)

    context = {
        "app": "notes",
        "form": form,
        "action": "Add",
    }

    return render(request, "notes/form.html", context)


@login_required
def notes_filter(request):
    """Filter modal for standalone notes."""
    filter_session_key = "standalone_notes_filter"

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
    queryset = Note.objects.filter(matter__isnull=True)
    filter_obj = NotesFilter(filter_data, queryset=queryset)

    return render(request, "notes/filter.html", {"filter": filter_obj})


@login_required
def notes_order_by(request, order):
    """Sort standalone notes by field."""
    filter_session_key = "standalone_notes_filter"
    filter_data = request.session.get(filter_session_key, {})

    current_order = filter_data.get("order_by", "")
    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session[filter_session_key] = filter_data
    request.session.modified = True

    return redirect("notes:list")


@login_required
def notes_filter_keyword(request):
    """Filter standalone notes by keyword."""
    filter_session_key = "standalone_notes_filter"
    filter_data = request.session.get(filter_session_key, {})
    keyword = request.GET.get("keyword", "").strip()

    if keyword:
        filter_data["keyword"] = keyword
    else:
        filter_data.pop("keyword", None)

    request.session[filter_session_key] = filter_data
    request.session.modified = True

    context = {"app": "notes"} | get_notes_data(request)
    return render(request, "notes/table.html", context)


@login_required
def notes_filter_category(request, category):
    """Filter standalone notes by category."""
    filter_session_key = "standalone_notes_filter"
    filter_data = request.session.get(filter_session_key, {})
    filter_data["category"] = category
    request.session[filter_session_key] = filter_data
    request.session.modified = True

    return redirect("notes:list")


@login_required
def notes_filter_category_clear(request):
    """Clear category filter for standalone notes."""
    filter_session_key = "standalone_notes_filter"
    filter_data = request.session.get(filter_session_key, {})
    filter_data.pop("category", None)
    request.session[filter_session_key] = filter_data
    request.session.modified = True

    return redirect("notes:list")


@login_required
def notes_filter_topic(request, topic):
    """Filter standalone notes by topic."""
    filter_session_key = "standalone_notes_filter"
    filter_data = request.session.get(filter_session_key, {})
    filter_data["topic"] = topic
    request.session[filter_session_key] = filter_data
    request.session.modified = True

    return redirect("notes:list")


@login_required
def notes_filter_topic_clear(request):
    """Clear topic filter for standalone notes."""
    filter_session_key = "standalone_notes_filter"
    filter_data = request.session.get(filter_session_key, {})
    filter_data.pop("topic", None)
    request.session[filter_session_key] = filter_data
    request.session.modified = True

    return redirect("notes:list")


@login_required
def notes_filter_importance(request, importance):
    """Filter standalone notes by importance."""
    filter_session_key = "standalone_notes_filter"
    filter_data = request.session.get(filter_session_key, {})
    filter_data["importance"] = "" if importance == 0 else importance
    request.session[filter_session_key] = filter_data
    request.session.modified = True

    return redirect("notes:list")


@login_required
@require_POST
def note_category(request, note_id, value):
    """Update note category."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)
    note.category = value
    note.save(update_fields=["category"])
    return redirect("notes:list")


@login_required
@require_POST
def note_importance(request, note_id, value):
    """Update note importance."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)
    note.importance = value
    note.save(update_fields=["importance"])
    return redirect("notes:list")


def get_sidebar_sort(request):
    """Get the current sidebar sort order from session for standalone notes."""
    return request.session.get("standalone_notes_sidebar_sort", "-updated_at")


def get_sorted_standalone_notes(sort_order):
    """Get standalone notes with the specified sort order."""
    return Note.objects.filter(matter__isnull=True).order_by(sort_order)


@login_required
def note_view(request, note_id):
    """Standalone editor view for a note without a matter."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)

    # Update viewed_at timestamp
    note.viewed_at = timezone.now()
    note.save(update_fields=["viewed_at"])

    # Get all standalone notes for sidebar with sort order
    sort_order = get_sidebar_sort(request)
    notes = get_sorted_standalone_notes(sort_order)

    context = {
        "note": note,
        "notes": notes,
        "sidebar_sort_options": SIDEBAR_SORT_OPTIONS,
        "current_sort": sort_order,
    }
    return render(request, "notes/editor.html", context)


@login_required
def note_content_partial(request, note_id):
    """HTMX partial for switching notes in the editor."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)

    # Update viewed_at timestamp
    note.viewed_at = timezone.now()
    note.save(update_fields=["viewed_at"])

    context = {
        "note": note,
    }
    return render(request, "notes/editor-content.html", context)


@login_required
def sidebar_sort(request, note_id, sort_key):
    """Change sidebar sort order and return updated sidebar list."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)

    # Validate sort key
    valid_keys = [key for key, _ in SIDEBAR_SORT_OPTIONS]
    if sort_key not in valid_keys:
        sort_key = "-updated_at"

    # Save to session
    request.session["standalone_notes_sidebar_sort"] = sort_key

    # Get sorted notes
    notes = get_sorted_standalone_notes(sort_key)

    context = {
        "note": note,
        "notes": notes,
        "sidebar_sort_options": SIDEBAR_SORT_OPTIONS,
        "current_sort": sort_key,
    }
    return render(request, "notes/sidebar-list.html", context)


@login_required
def note_edit(request, note_id):
    """Edit note metadata (title, category, date)."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)

    if request.method == "POST":
        form = NoteForm(request.POST, instance=note, use_required_attribute=False)
        if form.is_valid():
            form.save()
            return HttpResponse(status=204, headers={"HX-Trigger": "notesChanged"})
    else:
        form = NoteForm(instance=note, use_required_attribute=False)

    context = {
        "app": "notes",
        "note": note,
        "form": form,
        "action": "Edit",
    }

    return render(request, "notes/form.html", context)


@login_required
@require_POST
def note_delete(request, note_id):
    """Delete a standalone note."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)
    note.delete()

    return HttpResponse(status=204, headers={"HX-Trigger": "notesChanged"})


@login_required
def note_content(request, note_id):
    """GET returns markdown content, POST saves it."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)

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
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)

    content = request.POST.get("content", "")
    note.content = content
    note.save(update_fields=["content", "updated_at"])

    return JsonResponse({"saved": True, "updated_at": note.updated_at.isoformat()})


@login_required
@require_POST
def note_title(request, note_id):
    """Update note title."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)

    title = request.POST.get("title", "").strip()
    if title:
        note.title = title
        note.save(update_fields=["title", "updated_at"])
        return JsonResponse({"saved": True, "title": note.title})

    return JsonResponse({"saved": False, "error": "Title cannot be empty"}, status=400)


@login_required
def notes_shortcuts(request):
    """Show keyboard shortcuts modal."""
    return render(request, "notes/shortcuts-modal.html")


@login_required
def note_import_modal(request, note_id):
    """Show import markdown modal."""
    return render(request, "notes/import-modal.html")


@login_required
def reference_search(request, note_id):
    """Search documents and highlights for note references.

    For standalone notes without a matter, this returns empty results
    since there are no associated documents or highlights.
    """
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)
    query = request.GET.get("q", "").strip()

    # Standalone notes don't have access to matter-specific documents/highlights
    context = {
        "note": note,
        "documents": [],
        "highlights": [],
        "query": query,
    }
    return render(request, "notes/reference-results.html", context)


@login_required
def reference_citations(request, note_id):
    """Return current citations for references.

    For standalone notes, this returns an empty dictionary
    since there are no associated documents or highlights.
    """
    return JsonResponse({})
