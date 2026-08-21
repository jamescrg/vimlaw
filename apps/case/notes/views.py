import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from apps.case.views import get_matter_from_url
from apps.notes.models import Note, NoteFolder
from apps.notes.views import _next_untitled


@login_required
@require_POST
def notes_add(request, matter_id):
    """Create a matter note instantly (no modal), optionally into one of the
    matter's folders (?folder=<id>), auto-named among its siblings. The
    noteCreated trigger opens the new note in the editor (in-place swap,
    no navigation).
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
    return HttpResponse(
        status=204,
        headers={"HX-Trigger": json.dumps({"noteCreated": {"id": note.id}})},
    )
