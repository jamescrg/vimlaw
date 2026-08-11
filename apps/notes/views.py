import json

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.db.models.functions import Lower
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
from apps.matters.models import Matter

from .filters import NotesFilter
from .forms import NoteFolderForm, NoteFolderMoveForm, NoteForm
from .models import Note, NoteFolder, NoteView
from .tasks import queue_library_summary_sweep, queue_note_summary

NOTES_TRIGGER = "notesChanged"


# ---------------------------------------------------------------------------
# Tree-building utilities
# ---------------------------------------------------------------------------


def build_note_folder_tree_flat(folders_qs, expanded_ids):
    """Build a flat list of tree nodes from a queryset of folders.

    Returns list of dicts:
        {"folder": f, "level": 0-3, "parent_id": int|None,
         "has_children": bool, "is_expanded": bool, "is_visible": bool,
         "in_library": bool, "own_library_flag": bool}
    """
    folders = list(folders_qs.select_related("parent").order_by("name"))

    # Build parent→children map
    children_map = {}
    for f in folders:
        pid = f.parent_id
        children_map.setdefault(pid, []).append(f)

    # Build flat list via DFS
    result = []

    def _walk(parent_id, parent_visible, parent_in_library):
        for f in children_map.get(parent_id, []):
            is_expanded = f.pk in expanded_ids
            has_children = f.pk in children_map
            is_visible = parent_visible
            in_library = f.ai_library or parent_in_library
            result.append(
                {
                    "folder": f,
                    "level": f.depth,
                    "parent_id": f.parent_id,
                    "has_children": has_children,
                    "is_expanded": is_expanded,
                    "is_visible": is_visible,
                    "in_library": in_library,
                    "own_library_flag": f.ai_library,
                }
            )
            child_visible = is_visible and is_expanded
            _walk(f.pk, child_visible, in_library)

    _walk(None, True, False)  # Root folders always visible
    return result


def _folder_subtree_height(folder):
    """0-based height of folder's subtree: deepest descendant depth - own depth."""
    descendants = folder.get_descendants()
    if not descendants:
        return 0
    return max(d.depth for d in descendants) - folder.depth


def get_valid_move_targets(exclude_folder):
    """Return folders that can accept exclude_folder as a child.

    Same tree only (general or the folder's matter); excludes the folder
    itself, its descendants, and any target shallow enough that the moved
    subtree would exceed the 4-level depth cap.
    """
    descendant_ids = [d.pk for d in exclude_folder.get_descendants()]
    exclude_ids = [exclude_folder.pk] + descendant_ids
    height = _folder_subtree_height(exclude_folder)
    return (
        NoteFolder.objects.filter(
            depth__lt=3 - height, matter_id=exclude_folder.matter_id
        )
        .exclude(pk__in=exclude_ids)
        .order_by("name")
    )


def validate_folder_move(folder, destination):
    """Return an error message, or None if re-parenting is legal (None dest = root).

    The depth-cap check NoteFolder.clean() would do if the move paths didn't
    save with update_fields (which skips full_clean).
    """
    if destination is None:
        return None
    if destination.matter_id != folder.matter_id:
        return "Folders cannot move between matters."
    if destination.pk == folder.pk:
        return "A folder cannot be moved into itself."
    if any(d.pk == destination.pk for d in folder.get_descendants()):
        return "A folder cannot be moved into its own subfolder."
    if destination.depth + 1 + _folder_subtree_height(folder) > 3:
        return "Maximum folder depth (4 levels) exceeded."
    return None


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def get_note_folders_data(request):
    """Get note folders tree and selected folder from session (Notes tab =
    general tree only; matter trees live in the editor's Matters pane)."""
    folders = NoteFolder.objects.filter(matter__isnull=True)
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


def _build_tree(folders, notes_by_folder, expanded_ids):
    """Nested tree from name-ordered folders + per-folder note lists.

    Node = {"folder", "children": [node...], "notes": [Note...], "is_expanded"}.
    """
    nodes = {
        f.pk: {
            "folder": f,
            "children": [],
            "notes": notes_by_folder.get(f.pk, []),
            "is_expanded": f.pk in expanded_ids,
        }
        for f in folders
    }
    roots = []
    for f in folders:  # two-pass: a child's parent may sort after it
        parent = nodes.get(f.parent_id)
        (parent["children"] if parent else roots).append(nodes[f.pk])
    return roots


def get_editor_file_tree(request, note):
    """Both left-panel trees for the editor: the general Files tree and the
    per-matter trees of the Matters pane.

    Folder expansion comes from the session key shared with the Notes tab;
    matter-node expansion from its own session key. Both are unioned with
    the current note's chain (union not persisted) so the active note is
    always revealed.
    """
    expanded_ids = set(request.session.get("note_folders_expanded", []))
    if note.folder_id:
        expanded_ids |= {a.pk for a in note.folder.get_ancestors()}
        expanded_ids.add(note.folder_id)

    open_matters = list(Matter.objects.filter(status="Open").order_by("name"))
    if note.matter and note.matter not in open_matters:
        # Closed matter opened directly: surface it so the active pill exists
        open_matters.append(note.matter)
    matter_ids = {m.id for m in open_matters}

    expanded_matter_ids = set(request.session.get("note_matters_expanded", []))
    if note.matter_id:
        expanded_matter_ids.add(note.matter_id)

    folders_by_matter = {}
    for f in NoteFolder.objects.order_by(Lower("name")):
        folders_by_matter.setdefault(f.matter_id, []).append(f)

    notes_by_scope = {}  # matter_id -> {folder_id: [Note]}
    note_qs = Note.objects.filter(
        Q(matter__isnull=True) | Q(matter_id__in=matter_ids)
    ).order_by(Lower("title"))
    for n in note_qs:
        notes_by_scope.setdefault(n.matter_id, {}).setdefault(n.folder_id, []).append(n)

    general = notes_by_scope.get(None, {})
    matters = [
        {
            "matter": m,
            "file_tree": _build_tree(
                folders_by_matter.get(m.id, []),
                notes_by_scope.get(m.id, {}),
                expanded_ids,
            ),
            "root_notes": notes_by_scope.get(m.id, {}).get(None, []),
            "is_expanded": m.id in expanded_matter_ids,
        }
        for m in open_matters
    ]

    return {
        "file_tree": _build_tree(
            folders_by_matter.get(None, []), general, expanded_ids
        ),
        "root_notes": general.get(None, []),
        "matters": matters,
        "active_pane": "matters" if note.matter_id else "files",
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
        form = NoteForm(request.POST, user=request.user, use_required_attribute=False)
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
        form = NoteForm(user=request.user, use_required_attribute=False)

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
    return render(request, "notes/list.html", context)


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


@login_required
def note_view(request, note_id):
    """Standalone editor view for a note without a matter."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)

    # Record user's view of this note
    record_note_view(request.user, note)

    context = {"note": note} | get_editor_file_tree(request, note)
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
def editor_file_tree(request):
    """Left-panel trees partial for the editor (refreshed after DnD/CRUD).

    The current note comes as ?note=<id> because the client tracks it: the
    trees are not re-rendered on htmx note switches, so a note id baked
    into a path-param URL at page load would go stale.
    """
    note_id = request.GET.get("note", "")
    if not note_id.isdigit():
        return HttpResponse("note parameter required", status=400)
    note = get_object_or_404(Note, pk=note_id)
    context = {"note": note} | get_editor_file_tree(request, note)
    return render(request, "notes/editor-trees.html", context)


@login_required
def note_edit(request, note_id):
    """Edit note metadata (title, category, date)."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)

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
        queue_note_summary(note.id)
        return HttpResponse(status=204)

    return HttpResponse(note.content, content_type="text/plain; charset=utf-8")


@login_required
@require_POST
def note_autosave(request, note_id):
    """Autosave endpoint for the editor."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)

    content = request.POST.get("content", "")
    note.content = content
    # updated_by is set by AuditMixin.save; include it in update_fields so the
    # change is actually persisted.
    note.save(update_fields=["content", "updated_at", "updated_by"])
    queue_note_summary(note.id)

    return JsonResponse({"saved": True, "updated_at": note.updated_at.isoformat()})


@login_required
@require_POST
def note_title(request, note_id):
    """Update note title."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)

    title = request.POST.get("title", "").strip()
    if title:
        note.title = title
        note.save(update_fields=["title", "updated_at", "updated_by"])
        return JsonResponse({"saved": True, "title": note.title})

    return JsonResponse({"saved": False, "error": "Title cannot be empty"}, status=400)


@login_required
@require_POST
def note_set_ai(request, note_id, state):
    """Set the ai_context state on a standalone note (auto/always/never)."""
    if state not in ("auto", "always", "never"):
        return HttpResponse(status=400)

    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)
    note.ai_context = state
    note.save(update_fields=["ai_context", "updated_at", "updated_by"])
    if state != "never":
        queue_note_summary(note.id)

    return render(request, "notes/ai-context-cell.html", {"note": note})


@login_required
def note_meta(request, note_id):
    """Render the note meta partial (used by HTMX to refresh after autosave)."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=True)
    return render(request, "notes/meta.html", {"note": note})


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


def _editor_crud_response():
    """Editor-context success: refresh the trees and close the modal."""
    return HttpResponse(
        status=204,
        headers={
            "HX-Trigger": json.dumps({"noteFoldersChanged": True, "closeModal": True})
        },
    )


@login_required
def note_folder_add(request):
    """Add a note folder (Notes-tab modal, or editor context menu).

    Editor context arrives as ?context=editor plus either ?parent=<id>
    ("New subfolder", matter inherited from the parent) or ?matter=<id>
    ("New folder" at a matter's root).
    """
    editor = request.GET.get("context") == "editor"
    parent_id = request.GET.get("parent", "")
    matter_id = request.GET.get("matter", "")
    parent = matter = None
    if parent_id.isdigit():
        parent = get_object_or_404(NoteFolder, pk=parent_id)
        matter = parent.matter
    elif matter_id.isdigit():
        matter = get_object_or_404(Matter, pk=matter_id)

    if request.method == "POST":
        form = NoteFolderForm(request.POST, matter=matter)
        if form.is_valid():
            form.save()
            if form.cleaned_data.get("ai_library"):
                queue_library_summary_sweep()
            if editor:
                return _editor_crud_response()
            context = get_note_folders_data(request)
            response = render(request, "note_folders/list.html", context)
            response.status_code = 202
            response["HX-Trigger-After-Swap"] = "closeModal"
            return response
    else:
        form = NoteFolderForm(matter=matter)
        if parent and parent.can_have_children():
            form.initial["parent"] = parent.pk
        elif not editor:
            # Notes tab: pre-fill parent if a folder is currently selected
            selected_folder_id = request.session.get("notes_selected_folder_id")
            if selected_folder_id:
                try:
                    selected = NoteFolder.objects.get(pk=selected_folder_id)
                    if selected.can_have_children():
                        form.initial["parent"] = selected.pk
                except NoteFolder.DoesNotExist:
                    pass

    query = request.GET.urlencode()
    context = {
        "form": form,
        "action": "/notes/folders/add/" + (f"?{query}" if query else ""),
        "edit": False,
        "editor_context": editor,
    }
    return render(request, "note_folders/form.html", context)


@login_required
def note_folder_edit(request, folder_id):
    """Edit a note folder (Notes-tab modal, or editor context menu)."""
    folder = get_object_or_404(NoteFolder, pk=folder_id)
    editor = request.GET.get("context") == "editor"

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
            if "ai_library" in form.changed_data or "parent" in form.changed_data:
                queue_library_summary_sweep()
            if editor:
                return _editor_crud_response()
            context = get_note_folders_data(request)
            response = render(request, "note_folders/list.html", context)
            response.status_code = 202
            response["HX-Trigger-After-Swap"] = "closeModal"
            return response
    else:
        form = NoteFolderForm(instance=folder, exclude_folder=folder)

    query = request.GET.urlencode()
    context = {
        "form": form,
        "action": f"/notes/folders/edit/{folder_id}" + (f"?{query}" if query else ""),
        "edit": True,
        "folder": folder,
        "editor_context": editor,
        "extra_qs": query if editor else "",
    }
    return render(request, "note_folders/form.html", context)


@login_required
def note_folder_delete_confirm(request, folder_id):
    """Show delete confirmation for a note folder."""
    folder = get_object_or_404(NoteFolder, pk=folder_id)
    note_count = Note.objects.filter(folder=folder).count()
    descendants = folder.get_descendants()
    subfolder_count = len(descendants)

    # Editor context (plus the open note's id) rides the querystring so the
    # delete endpoint can redirect if the open note gets deleted with the
    # folder.
    editor = request.GET.get("context") == "editor"
    context = {
        "folder": folder,
        "note_count": note_count,
        "subfolder_count": subfolder_count,
        "extra_qs": request.GET.urlencode() if editor else "",
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

    # Editor context: if the open note went down with the folder, a plain
    # refresh would 404 — send the user to the notes index instead.
    note_id = request.GET.get("note", "")
    if (
        request.GET.get("context") == "editor"
        and note_id.isdigit()
        and not Note.objects.filter(pk=note_id).exists()
    ):
        return HttpResponse(status=204, headers={"HX-Redirect": reverse("notes:index")})

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
            queue_library_summary_sweep()

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


def _expand_folder_in_session(request, folder_id):
    """Idempotently mark a folder expanded (shared Notes-tab/editor session key)."""
    expanded = request.session.get("note_folders_expanded", [])
    if folder_id not in expanded:
        expanded.append(folder_id)
        request.session["note_folders_expanded"] = expanded
        request.session.modified = True


@login_required
@require_POST
def note_folder_reparent(request, folder_id):
    """Re-parent a folder (editor tree drag-and-drop). 204, or 400 with a reason."""
    folder = get_object_or_404(NoteFolder, pk=folder_id)
    dest_id = request.POST.get("destination") or None
    if dest_id is not None and not dest_id.isdigit():
        return HttpResponse("Invalid destination.", status=400)
    destination = get_object_or_404(NoteFolder, pk=dest_id) if dest_id else None

    error = validate_folder_move(folder, destination)
    if error:
        return HttpResponse(error, status=400)

    folder.parent = destination
    folder.depth = destination.depth + 1 if destination else 0
    folder.save(update_fields=["parent", "depth"])
    folder.update_descendant_depths()
    queue_library_summary_sweep()  # subtree may enter/leave an AI library
    if destination:
        _expand_folder_in_session(request, destination.pk)
    return HttpResponse(status=204)


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
def note_matter_toggle_expand(request, matter_id):
    """Toggle a matter node's expand state in the editor's Matters pane."""
    expanded = request.session.get("note_matters_expanded", [])
    if matter_id in expanded:
        expanded.remove(matter_id)
    else:
        expanded.append(matter_id)
    request.session["note_matters_expanded"] = expanded
    request.session.modified = True
    return HttpResponse(status=204)


@login_required
@require_POST
def note_folder_toggle_all(request):
    """Expand or collapse all GENERAL folders in session.

    The session key is shared with the editor's matter trees, so matter
    folder ids already present must survive both directions.
    """
    expand = request.GET.get("expand") == "true"
    general_ids = set(
        NoteFolder.objects.filter(matter__isnull=True).values_list("pk", flat=True)
    )
    current = set(request.session.get("note_folders_expanded", []))
    updated = (current | general_ids) if expand else (current - general_ids)
    request.session["note_folders_expanded"] = list(updated)
    request.session.modified = True
    return HttpResponse(status=204)


@login_required
def note_move(request, note_id):
    """Move a note to a different folder (modal or editor drag-and-drop).

    Serves general AND matter notes; the destination must live in the
    note's own tree. note.matter is never written here.
    """
    note = get_object_or_404(Note, pk=note_id)
    all_folders = NoteFolder.objects.filter(matter_id=note.matter_id)

    if request.method == "POST":
        folder_id = request.POST.get("destination")
        if folder_id:
            folder = get_object_or_404(NoteFolder, pk=folder_id)
            if folder.matter_id != note.matter_id:
                return HttpResponse(
                    "Notes cannot move into another matter's folders.", status=400
                )
            note.folder = folder
        else:
            note.folder = None
        note.save(update_fields=["folder"])
        queue_note_summary(note.id)
        if note.folder_id:
            _expand_folder_in_session(request, note.folder_id)
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
            # Notes-tab bulk move handles general notes only, so the
            # destination must be a general folder
            folder = get_object_or_404(NoteFolder, pk=folder_id, matter__isnull=True)
        else:
            folder = None
        Note.objects.filter(id__in=selected, matter__isnull=True).update(folder=folder)
        clear_selected_ids(request, key)
        queue_library_summary_sweep()
        return HttpResponse(status=204, headers={"HX-Trigger": NOTES_TRIGGER})

    all_folders = NoteFolder.objects.filter(matter__isnull=True)
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
