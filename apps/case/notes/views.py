from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.case.models import Document, Highlight, Note
from apps.case.views import get_matter_from_url, get_session_key

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

    return {
        "notes": notes,
        "current_order": current_order,
        "keyword": keyword,
        "importances": list(range(1, 11)),
        "importance_value": importance_value,
        "selected_importance": (
            f"Importance {importance_value}" if importance_value else ""
        ),
        "category_choices": Note.CATEGORY_CHOICES,
        "selected_category": selected_category,
        "selected_category_key": category_key,
    }


@login_required
def notes_index(request, matter_id):
    """Main notes view."""
    matter, matters = get_matter_from_url(request, matter_id)

    context = {
        "app": "documents",
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
        "app": "documents",
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
        form = NoteForm(request.POST, use_required_attribute=False)
        if form.is_valid():
            note = form.save(commit=False)
            note.user = request.user
            note.matter = matter
            note.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "notesChanged"})
    else:
        form = NoteForm(use_required_attribute=False)

    context = {
        "app": "documents",
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

    # Update viewed_at timestamp
    note.viewed_at = timezone.now()
    note.save(update_fields=["viewed_at"])

    context = {
        "note": note,
        "matter": matter,
    }
    return render(request, "case/notes/editor.html", context)


@login_required
def note_edit(request, note_id):
    """Edit note metadata (title, importance)."""
    note = get_object_or_404(Note, pk=note_id)
    matter = note.matter

    if request.method == "POST":
        form = NoteForm(request.POST, instance=note, use_required_attribute=False)
        if form.is_valid():
            form.save()
            return HttpResponse(status=204, headers={"HX-Trigger": "notesChanged"})
    else:
        form = NoteForm(instance=note, use_required_attribute=False)

    context = {
        "app": "documents",
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
    note.save(update_fields=["content", "updated_at"])

    return JsonResponse({"saved": True, "updated_at": note.updated_at.isoformat()})


@login_required
@require_POST
def note_title(request, note_id):
    """Update note title."""
    note = get_object_or_404(Note, pk=note_id)

    title = request.POST.get("title", "").strip()
    if title:
        note.title = title
        note.save(update_fields=["title", "updated_at"])
        return JsonResponse({"saved": True, "title": note.title})

    return JsonResponse({"saved": False, "error": "Title cannot be empty"}, status=400)


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
def notes_shortcuts(request, matter_id):
    """Show keyboard shortcuts modal."""
    return render(request, "case/notes/shortcuts-modal.html")


@login_required
def note_import_modal(request, note_id):
    """Show import markdown modal."""
    return render(request, "case/notes/import-modal.html")


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
    return render(request, "case/notes/reference-results.html", context)


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
