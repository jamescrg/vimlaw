import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

import apps.drive.google as drive_google
from apps.accounts.access import filter_matters_for_user
from apps.case.models import Document, Highlight
from apps.case.views import get_matter_from_url
from apps.matters.models import Matter
from apps.notes.models import Note, NoteFolder
from apps.notes.views import (
    _expand_folder_in_session,
    _next_untitled,
    get_editor_file_tree,
    record_note_view,
)


@login_required
@require_POST
def notes_add(request, matter_id):
    """Create a matter note instantly (no modal), optionally into one of the
    matter's folders (?folder=<id>), auto-named among its siblings. The
    HX-Redirect opens the new note in the editor.
    """
    matter, matters = get_matter_from_url(request, matter_id)

    folder = None
    folder_id = request.GET.get("folder", "")
    if folder_id.isdigit():
        folder = get_object_or_404(NoteFolder, pk=folder_id)
        if folder.matter_id != matter.id:
            return HttpResponse("Folder belongs to another matter.", status=400)

    siblings = Note.objects.filter(matter=matter, folder=folder).values_list(
        "title", flat=True
    )
    note = Note.objects.create(
        title=_next_untitled(siblings),
        author=request.user,
        matter=matter,
        folder=folder,
    )
    if folder:
        _expand_folder_in_session(request, folder.pk)
    return HttpResponse(
        status=204,
        headers={"HX-Redirect": reverse("case:note-view", args=[note.id])},
    )


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
@require_POST
def note_delete(request, note_id):
    """Delete a note."""
    note = get_object_or_404(Note, pk=note_id)
    note.delete()

    return HttpResponse(status=204, headers={"HX-Trigger": "notesChanged"})


@login_required
def note_properties(request, note_id):
    """Properties modal for a matter note (AI context + matter re-assign)."""
    from apps.notes.models import AI_CONTEXT_CHOICES

    note = get_object_or_404(Note, pk=note_id, matter__isnull=False)
    matters = filter_matters_for_user(
        Matter.objects.filter(status="Open").order_by("name"), request.user
    )
    context = {"note": note, "ai_choices": AI_CONTEXT_CHOICES, "matters": matters}
    return render(request, "notes/properties-modal.html", context)


@login_required
@require_POST
def note_reassign_matter(request, note_id):
    """Move a matter note to another matter; folder resets to that matter's
    root (a folder always belongs to exactly one matter's tree)."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=False)
    matter = get_object_or_404(
        filter_matters_for_user(Matter.objects.filter(status="Open"), request.user),
        pk=request.POST.get("matter"),
    )
    if matter.id != note.matter_id:
        note.matter = matter
        note.folder = None
        note.save(update_fields=["matter", "folder"])
    return HttpResponse(
        status=204,
        headers={
            "HX-Trigger": json.dumps({"noteFoldersChanged": True, "closeModal": True})
        },
    )


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
def notes_shortcuts(request, matter_id):
    """Show keyboard shortcuts modal."""
    return render(request, "notes/shortcuts-modal.html")


@login_required
def note_import_modal(request, note_id):
    """Show import markdown modal."""
    return render(request, "notes/import-modal.html")


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

    return HttpResponse(status=204)


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
    return render(request, "case/documents/drive-link-modal.html", context)


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
