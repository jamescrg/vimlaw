"""JSON API for the notes library.

Consumed by the Claude Desktop MCP server (tools/kosmos_notes_mcp.py) so a
Desktop conversation can list, read, and search the user's notes. Auth is
the same per-user X-Kosmos-Token bearer key the LibreOffice companion uses
(CompanionToken, via kosmos_api_auth) with a 401 body that carries setup
guidance the model relays verbatim.

Reads are unrestricted within the user's access; the single write path
(api_note_write, append/replace) is additionally gated per note by the
editor's AI-write toggle, a 24-hour grant stored in Note.ai_write_until.
Notes cannot be created or deleted from here.

Access mirrors the app: general (library) notes are shared, matter notes
are gated by has_matter_access, and matter listings/scopes cover the
user's accessible OPEN matters only (matching the editor tree, not the
palette, which also spans concluded matters).
"""

import json

from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.access import filter_matters_for_user
from apps.drafts.api_auth import (
    TOKEN_HELP,
    kosmos_api_auth as notes_api_auth,
)
from apps.matters.models import Matter

from .models import Note
from .views import (
    _HL_START,
    _HL_STOP,
    _folder_path_index,
    _palette_search,
    _parse_note_scope,
)

__all__ = ["TOKEN_HELP", "notes_api_auth"]

MATTER_404 = "No such matter, or you do not have access to it."
NOTE_404 = "No such note, or you do not have access to it."
WRITE_403 = (
    "AI write access is not enabled for this note. Ask the user to open "
    "the note in the Kosmos editor and click the sparkles button in the "
    "toolbar, which grants write access for 24 hours."
)

SEARCH_LIMIT_DEFAULT = 20
SEARCH_LIMIT_MAX = 100


def _open_matters(user):
    return filter_matters_for_user(Matter.objects.filter(status="Open"), user)


def _display_path(matter_name, folder_parts, title):
    return "/".join(([matter_name] if matter_name else []) + folder_parts + [title])


def _note_payload(note):
    """Common fields for a fully-loaded Note (select_related matter+folder)."""
    folder_parts = (
        [f.name for f in note.folder.get_ancestors() + [note.folder]]
        if note.folder
        else []
    )
    matter_name = note.matter.name if note.matter_id else None
    return {
        "id": note.id,
        "title": note.title,
        "path": _display_path(matter_name, folder_parts, note.title),
        "matter_id": note.matter_id,
        "matter": matter_name,
        "updated_at": note.updated_at.isoformat(),
    }


@notes_api_auth
@require_GET
def api_matters(request):
    """Accessible open matters, name-ordered; ?q= filters by name."""
    matters = _open_matters(request.api_user).order_by("name")
    q = (request.GET.get("q") or "").strip()
    if q:
        matters = matters.filter(name__icontains=q)
    return JsonResponse({"matters": [{"id": m.id, "name": m.name} for m in matters]})


@notes_api_auth
@require_GET
def api_notes(request):
    """Flat note manifest. ?scope= all (default) | library | matters |
    matter:<id>."""
    try:
        scope_key, scope, _ = _parse_note_scope(
            request.api_user,
            request.GET.get("scope") or "all",
            matter_qs=Matter.objects.filter(status="Open"),
        )
    except Http404:
        return JsonResponse({"error": MATTER_404}, status=404)

    folder_path = _folder_path_index()
    notes = []
    for row in scope.values(
        "id", "title", "folder_id", "matter_id", "matter__name", "updated_at", "summary"
    ).order_by("-updated_at"):
        notes.append(
            {
                "id": row["id"],
                "title": row["title"],
                "path": _display_path(
                    row["matter__name"], folder_path(row["folder_id"]), row["title"]
                ),
                "matter_id": row["matter_id"],
                "matter": row["matter__name"],
                "updated_at": row["updated_at"].isoformat(),
                "summary": row["summary"],
            }
        )
    return JsonResponse({"scope": scope_key, "notes": notes})


@notes_api_auth
@require_GET
def api_note(request, note_id):
    """Full markdown content of one note. Access mirrors _get_note: general
    notes are shared, matter notes need matter access (404 either way, so
    denial doesn't confirm existence)."""
    note = Note.objects.select_related("matter", "folder").filter(pk=note_id).first()
    if note is None or (
        note.matter_id and not request.api_user.has_matter_access(note.matter)
    ):
        return JsonResponse({"error": NOTE_404}, status=404)
    return JsonResponse(dict(_note_payload(note), content=note.content))


@notes_api_auth
@require_POST
def api_note_write(request, note_id):
    """Append to or replace one note's markdown content.

    Gated per note by the editor's AI-write toggle (Note.ai_write_until,
    a 24-hour grant). Body: {"content": str, "mode": "append"|"replace"}
    (default append; unknown modes fall back to append, matching the
    in-app edit-note block). Content is stored as plain markdown; in-app
    [doc:]/[hl:] handles are not resolved here. The save bumps
    updated_at and lands in the note's history like any other edit.
    """
    note = Note.objects.select_related("matter", "folder").filter(pk=note_id).first()
    if note is None or (
        note.matter_id and not request.api_user.has_matter_access(note.matter)
    ):
        return JsonResponse({"error": NOTE_404}, status=404)
    if not (note.ai_write_until and note.ai_write_until > timezone.now()):
        return JsonResponse({"error": WRITE_403}, status=403)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = None
    if not isinstance(body, dict):
        return JsonResponse(
            {"error": "Request body must be a JSON object."}, status=400
        )
    content = (body.get("content") or "").strip()
    if not content:
        return JsonResponse({"error": "content is required."}, status=400)
    mode = "replace" if body.get("mode") == "replace" else "append"

    if mode == "replace":
        note.content = content
    else:
        note.content = (note.content.rstrip() + "\n\n" + content).strip()
    note.save()
    verb = "Rewrote" if mode == "replace" else "Appended to"
    return JsonResponse(
        dict(_note_payload(note), message=f"{verb} note: **{note.title}**")
    )


@notes_api_auth
@require_GET
def api_search(request):
    """Ranked search over the palette's two bands. ?q= (min 2 chars),
    ?scope= as in api_notes, ?limit= caps each band (default 20, max 100).
    Excerpts are plain text with matches wrapped in ** markers."""
    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse(
            {"error": "Query must be at least 2 characters."}, status=400
        )
    try:
        scope_key, scope, _ = _parse_note_scope(
            request.api_user,
            request.GET.get("scope") or "all",
            matter_qs=Matter.objects.filter(status="Open"),
        )
    except Http404:
        return JsonResponse({"error": MATTER_404}, status=404)

    limit_raw = request.GET.get("limit", "")
    limit = (
        min(int(limit_raw), SEARCH_LIMIT_MAX)
        if limit_raw.isdigit() and int(limit_raw) > 0
        else SEARCH_LIMIT_DEFAULT
    )
    title_notes, content_notes = _palette_search(
        q, scope, title_limit=limit, content_limit=limit
    )
    return JsonResponse(
        {
            "scope": scope_key,
            "query": q,
            "title_matches": [_note_payload(n) for n in title_notes],
            "content_matches": [
                dict(
                    _note_payload(n),
                    excerpt=n.excerpt.replace(_HL_START, "**").replace(_HL_STOP, "**"),
                )
                for n in content_notes
            ],
        }
    )
