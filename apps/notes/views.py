from django.contrib.auth.decorators import login_required
from django.db.models import F, OuterRef, Subquery
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.management.pagination import CustomPaginator
from apps.management.selection import (
    all_visible_selected,
    clear_selected_ids,
    get_selected_ids,
    get_session_key,
    select_all_ids,
    selection_response,
    toggle_id,
)

from .filters import NotesFilter
from .forms import NoteFolderForm, NoteFolderMoveForm, NoteForm
from .models import Note, NoteFolder, NoteView

NOTES_TRIGGER = "notesChanged"

SIDEBAR_SORT_OPTIONS = [
    ("-viewed_at", "Recently viewed"),
    ("-updated_at", "Modified, new to old"),
    ("-created_at", "Created, new to old"),
    ("title", "Title (A-Z)"),
]


# ---------------------------------------------------------------------------
# Tree-building utilities
# ---------------------------------------------------------------------------


def build_note_folder_tree_flat(folders_qs, expanded_ids):
    """Build a flat list of tree nodes from a queryset of folders.

    Returns list of dicts:
        {"folder": f, "level": 0-3, "parent_id": int|None,
         "has_children": bool, "is_expanded": bool, "is_visible": bool}
    """
    folders = list(folders_qs.select_related("parent").order_by("name"))

    # Build parent→children map
    children_map = {}
    for f in folders:
        pid = f.parent_id
        children_map.setdefault(pid, []).append(f)

    # Build flat list via DFS
    result = []

    def _walk(parent_id, parent_visible):
        for f in children_map.get(parent_id, []):
            is_expanded = f.pk in expanded_ids
            has_children = f.pk in children_map
            is_visible = parent_visible
            result.append(
                {
                    "folder": f,
                    "level": f.depth,
                    "parent_id": f.parent_id,
                    "has_children": has_children,
                    "is_expanded": is_expanded,
                    "is_visible": is_visible,
                }
            )
            child_visible = is_visible and is_expanded
            _walk(f.pk, child_visible)

    _walk(None, True)  # Root folders always visible
    return result


def get_valid_move_targets(exclude_folder):
    """Return folders excluding the given folder, its descendants, and depth-3 folders."""
    descendant_ids = [d.pk for d in exclude_folder.get_descendants()]
    exclude_ids = [exclude_folder.pk] + descendant_ids
    return (
        NoteFolder.objects.filter(depth__lt=3)
        .exclude(pk__in=exclude_ids)
        .order_by("name")
    )


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def get_note_folders_data(request):
    """Get note folders tree and selected folder from session."""
    folders = NoteFolder.objects.all()
    expanded_ids = set(request.session.get("note_folders_expanded", []))
    selected_folder_id = request.session.get("notes_selected_folder_id")

    tree = build_note_folder_tree_flat(folders, expanded_ids)

    if selected_folder_id == "all":
        selected_folder = None
    elif selected_folder_id:
        try:
            selected_folder = NoteFolder.objects.get(pk=selected_folder_id)
        except NoteFolder.DoesNotExist:
            selected_folder = None
            request.session["notes_selected_folder_id"] = None
    else:
        selected_folder = None

    return {
        "note_folder_tree": tree,
        "selected_note_folder": selected_folder,
        "all_folders_selected": selected_folder_id == "all",
    }


def get_notes_data(request):
    """Get standalone notes data with filters applied from session."""
    filter_session_key = "standalone_notes_filter"
    filter_data = request.session.get(filter_session_key, {})

    queryset = Note.objects.filter(matter__isnull=True).order_by("-updated_at")

    # Apply folder filter
    selected_folder_id = request.session.get("notes_selected_folder_id")
    if selected_folder_id == "all":
        pass  # No folder filter — show all notes
    elif selected_folder_id:
        queryset = queryset.filter(folder_id=selected_folder_id)
    else:
        queryset = queryset.filter(folder_id__isnull=True)

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

    # Selection state
    session_key = get_session_key("selected_notes")
    selected_notes = get_selected_ids(request, session_key)
    visible_ids = [n.id for n in pagination.get_object_list()]

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
        "selected_notes": selected_notes,
        "all_selected": all_visible_selected(selected_notes, visible_ids),
    }


@login_required
def notes_index(request):
    """Main standalone notes list view."""
    context = (
        {
            "app": "notes",
        }
        | get_notes_data(request)
        | get_note_folders_data(request)
    )

    return render(request, "notes/main.html", context)


@login_required
def notes_list(request):
    """HTMX partial for standalone notes list."""
    context = (
        {
            "app": "notes",
        }
        | get_notes_data(request)
        | get_note_folders_data(request)
    )

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

            # Open new note in a new browser tab
            note_url = reverse("notes:note-view", args=[note.id])
            return HttpResponse(
                f'<script>window.open("{note_url}", "_blank");'
                "window.dispatchEvent(new CustomEvent('close-modal'));</script>",
                headers={"HX-Trigger": "notesChanged"},
            )
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
    return request.session.get("standalone_notes_sidebar_sort", "-viewed_at")


def record_note_view(user, note):
    """Record that a user viewed a note, updating or creating the NoteView record."""
    from django.utils import timezone

    NoteView.objects.update_or_create(
        user=user,
        note=note,
        defaults={},  # viewed_at is auto_now, so it updates automatically
    )

    note.viewed_at = timezone.now()
    note.save(update_fields=["viewed_at"])


def get_sorted_standalone_notes(user, sort_order="-viewed_at"):
    """Get standalone notes sorted by user's view history or specified order."""
    notes = Note.objects.filter(matter__isnull=True)

    if sort_order == "-viewed_at":
        # Sort by user's personal view history
        user_views = NoteView.objects.filter(
            user=user,
            note=OuterRef("pk"),
        ).values("viewed_at")[:1]

        notes = notes.annotate(user_viewed_at=Subquery(user_views)).order_by(
            F("user_viewed_at").desc(nulls_last=True)
        )
    else:
        notes = notes.order_by(sort_order)

    return notes[:20]


@login_required
def note_view(request, note_id):
    """Standalone editor view for a note without a matter."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)

    # Record user's view of this note
    record_note_view(request.user, note)

    # Get all standalone notes for sidebar with sort order
    sort_order = get_sidebar_sort(request)
    notes = get_sorted_standalone_notes(request.user, sort_order)

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

    # Record user's view of this note
    record_note_view(request.user, note)

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
        sort_key = "-viewed_at"

    # Save to session
    request.session["standalone_notes_sidebar_sort"] = sort_key

    # Get sorted notes
    notes = get_sorted_standalone_notes(request.user, sort_key)

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
        "action": "Rename",
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
    """Search documents and highlights for note references."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)
    query = request.GET.get("q", "").strip()

    context = {
        "note": note,
        "documents": [],
        "highlights": [],
        "query": query,
    }
    return render(request, "notes/reference-results.html", context)


@login_required
def reference_citations(request, note_id):
    """Return current citations for references."""
    return JsonResponse({})


# ---------------------------------------------------------------------------
# Note Folder views
# ---------------------------------------------------------------------------


@login_required
def note_folder_select(request, folder_id):
    """Select a note folder, filtering the notes list."""
    saved_folder = request.session.get("notes_selected_folder_id")
    if folder_id == saved_folder:
        request.session["notes_selected_folder_id"] = None
    else:
        request.session["notes_selected_folder_id"] = folder_id

    return redirect("notes:index")


@login_required
def note_folder_unsorted(request):
    """Show unsorted (no folder) notes."""
    request.session["notes_selected_folder_id"] = None
    return redirect("notes:index")


@login_required
def note_folder_all(request):
    """Show notes from all folders."""
    request.session["notes_selected_folder_id"] = "all"
    return redirect("notes:index")


@login_required
def note_folder_add(request):
    """Add a new note folder."""
    if request.method == "POST":
        form = NoteFolderForm(request.POST)
        if form.is_valid():
            form.save()
            context = get_note_folders_data(request)
            response = render(request, "note_folders/list.html", context)
            response.status_code = 202
            response["HX-Trigger-After-Swap"] = "closeModal"
            return response
    else:
        form = NoteFolderForm()
        # Pre-fill parent if a folder is currently selected
        selected_folder_id = request.session.get("notes_selected_folder_id")
        if selected_folder_id:
            try:
                selected = NoteFolder.objects.get(pk=selected_folder_id)
                if selected.can_have_children():
                    form.initial["parent"] = selected.pk
            except NoteFolder.DoesNotExist:
                pass

    context = {
        "form": form,
        "action": "/notes/folders/add/",
        "edit": False,
    }
    return render(request, "note_folders/form.html", context)


@login_required
def note_folder_edit(request, folder_id):
    """Edit a note folder."""
    folder = get_object_or_404(NoteFolder, pk=folder_id)

    if request.method == "POST":
        form = NoteFolderForm(request.POST, instance=folder, exclude_folder=folder)
        if form.is_valid():
            old_parent_id = (
                NoteFolder.objects.filter(pk=folder.pk)
                .values_list("parent_id", flat=True)
                .first()
            )
            folder = form.save()
            if folder.parent_id != old_parent_id:
                folder.update_descendant_depths()
            context = get_note_folders_data(request)
            response = render(request, "note_folders/list.html", context)
            response.status_code = 202
            response["HX-Trigger-After-Swap"] = "closeModal"
            return response
    else:
        form = NoteFolderForm(instance=folder, exclude_folder=folder)

    context = {
        "form": form,
        "action": f"/notes/folders/edit/{folder_id}",
        "edit": True,
        "folder": folder,
    }
    return render(request, "note_folders/form.html", context)


@login_required
def note_folder_delete_confirm(request, folder_id):
    """Show delete confirmation for a note folder."""
    folder = get_object_or_404(NoteFolder, pk=folder_id)
    note_count = Note.objects.filter(folder=folder).count()
    descendants = folder.get_descendants()
    subfolder_count = len(descendants)

    context = {
        "folder": folder,
        "note_count": note_count,
        "subfolder_count": subfolder_count,
    }
    return render(request, "note_folders/delete-confirm.html", context)


@login_required
def note_folder_delete(request, folder_id):
    """Delete a note folder with options for subfolders and notes."""
    folder = get_object_or_404(NoteFolder, pk=folder_id)
    delete_notes = request.GET.get("delete_notes")
    delete_subfolders = request.GET.get("delete_subfolders")

    descendants = folder.get_descendants()
    parent_folder = folder.parent

    if delete_subfolders:
        # Delete all descendant notes and subfolders
        for desc in reversed(descendants):
            Note.objects.filter(folder=desc).delete()
            desc.delete()
        if delete_notes:
            Note.objects.filter(folder=folder).delete()
    else:
        # Reparent subfolders to this folder's parent
        for child in folder.children.all():
            child.parent = parent_folder
            child.depth = parent_folder.depth + 1 if parent_folder else 0
            child.save(update_fields=["parent", "depth"])
            child.update_descendant_depths()

        if delete_notes:
            Note.objects.filter(folder=folder).delete()

    # Clear selected folder if it was this one
    if request.session.get("notes_selected_folder_id") == folder_id:
        request.session["notes_selected_folder_id"] = None

    folder.delete()

    return HttpResponse(status=204, headers={"HX-Refresh": "true"})


@login_required
def note_folder_move(request, folder_id):
    """Move a folder to a new parent via modal."""
    folder = get_object_or_404(NoteFolder, pk=folder_id)
    valid_targets = get_valid_move_targets(folder)

    if request.method == "POST":
        form = NoteFolderMoveForm(request.POST)
        form.fields["destination"].queryset = valid_targets
        if form.is_valid():
            destination = form.cleaned_data["destination"]
            folder.parent = destination
            folder.depth = destination.depth + 1 if destination else 0
            folder.save(update_fields=["parent", "depth"])
            folder.update_descendant_depths()

            context = get_note_folders_data(request)
            response = render(request, "note_folders/list.html", context)
            response.status_code = 202
            response["HX-Trigger-After-Swap"] = "closeModal"
            return response

    # Build tree for move modal — expand ancestors of current parent
    expanded_ids = set(a.pk for a in folder.get_ancestors()) if folder.parent else set()
    tree = build_note_folder_tree_flat(valid_targets, expanded_ids)

    context = {
        "folder": folder,
        "move_targets": tree,
        "valid_targets": valid_targets,
    }
    return render(request, "note_folders/move.html", context)


@login_required
@require_POST
def note_folder_toggle_expand(request, folder_id):
    """Toggle folder expand/collapse state in session."""
    expanded = request.session.get("note_folders_expanded", [])
    if folder_id in expanded:
        expanded.remove(folder_id)
    else:
        expanded.append(folder_id)
    request.session["note_folders_expanded"] = expanded
    request.session.modified = True
    return HttpResponse(status=204)


@login_required
@require_POST
def note_folder_toggle_all(request):
    """Expand or collapse all folders in session."""
    expand = request.GET.get("expand") == "true"
    if expand:
        all_ids = list(NoteFolder.objects.values_list("pk", flat=True))
        request.session["note_folders_expanded"] = all_ids
    else:
        request.session["note_folders_expanded"] = []
    request.session.modified = True
    return HttpResponse(status=204)


@login_required
def note_move(request, note_id):
    """Move a note to a different folder via modal."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)
    all_folders = NoteFolder.objects.all()

    if request.method == "POST":
        folder_id = request.POST.get("destination")
        if folder_id:
            note.folder = get_object_or_404(NoteFolder, pk=folder_id)
        else:
            note.folder = None
        note.save(update_fields=["folder"])
        return HttpResponse(status=204, headers={"HX-Trigger": "notesChanged"})

    # Build tree — expand ancestors of current folder so selection is visible
    if note.folder:
        expanded_ids = set(a.pk for a in note.folder.get_ancestors())
    else:
        expanded_ids = set()
    tree = build_note_folder_tree_flat(all_folders, expanded_ids)

    context = {
        "note": note,
        "move_targets": tree,
    }
    return render(request, "notes/move.html", context)


# ---------------------------------------------------------------------------
# Note multi-select views
# ---------------------------------------------------------------------------


@login_required
@require_POST
def notes_toggle_select(request, note_id):
    """Toggle a single note's selection."""
    get_object_or_404(Note, pk=note_id, matter__isnull=True)
    toggle_id(request, get_session_key("selected_notes"), note_id)
    return selection_response(NOTES_TRIGGER)


@login_required
@require_POST
def notes_select_all(request):
    """Select or deselect all visible notes."""
    visible_ids = [n.id for n in get_notes_data(request)["notes"]]
    select_all_ids(request, get_session_key("selected_notes"), visible_ids)
    return selection_response(NOTES_TRIGGER)


@login_required
@require_POST
def notes_clear_selection(request):
    """Clear all note selections."""
    clear_selected_ids(request, get_session_key("selected_notes"))
    return selection_response(NOTES_TRIGGER)


@login_required
@require_POST
def notes_bulk_set_importance(request):
    """Set importance on selected notes."""
    key = get_session_key("selected_notes")
    selected = get_selected_ids(request, key)
    if not selected:
        return HttpResponse(status=400, content="No notes selected.")

    importance = request.POST.get("importance")
    if importance:
        Note.objects.filter(id__in=selected, matter__isnull=True).update(
            importance=int(importance)
        )
        clear_selected_ids(request, key)

    return selection_response(NOTES_TRIGGER)


@login_required
def notes_bulk_move(request):
    """Move selected notes to a folder via modal."""
    key = get_session_key("selected_notes")
    selected = get_selected_ids(request, key)
    if not selected:
        return HttpResponse(status=400, content="No notes selected.")

    if request.method == "POST":
        folder_id = request.POST.get("destination")
        if folder_id:
            folder = get_object_or_404(NoteFolder, pk=folder_id)
        else:
            folder = None
        Note.objects.filter(id__in=selected, matter__isnull=True).update(folder=folder)
        clear_selected_ids(request, key)
        return HttpResponse(status=204, headers={"HX-Trigger": NOTES_TRIGGER})

    all_folders = NoteFolder.objects.all()
    tree = build_note_folder_tree_flat(all_folders, set())

    context = {
        "selected_count": len(selected),
        "move_targets": tree,
    }
    return render(request, "notes/bulk-move.html", context)


@login_required
@require_POST
def notes_bulk_delete(request):
    """Delete selected notes."""
    key = get_session_key("selected_notes")
    selected = get_selected_ids(request, key)
    if not selected:
        return HttpResponse(status=400, content="No notes selected.")

    Note.objects.filter(id__in=selected, matter__isnull=True).delete()
    clear_selected_ids(request, key)

    return selection_response(NOTES_TRIGGER)
