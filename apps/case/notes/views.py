from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

import apps.drive.google as drive_google
from apps.case.views import get_matter_from_url
from apps.matters.models import Matter
from apps.notes.models import Note, NoteFolder
from apps.notes.views import _expand_folder_in_session, _next_untitled


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
        headers={"HX-Redirect": reverse("notes:note-view", args=[note.id])},
    )


# ---------------------------------------------------------------------------
# Google Drive folder linking (Documents tab)
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
