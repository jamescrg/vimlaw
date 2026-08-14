import json
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.contrib.postgres.search import SearchHeadline, SearchQuery
from django.db.models import Q
from django.db.models.functions import Lower
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST
from watson import search as watson

from apps.accounts.access import filter_matters_for_user
from apps.matters.models import Matter

from .forms import NoteFolderForm
from .models import Note, NoteFolder, NoteView
from .tasks import queue_note_summary

# ---------------------------------------------------------------------------
# Tree-building utilities
# ---------------------------------------------------------------------------


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


def _build_tree(folders, notes_by_folder):
    """Nested tree from name-ordered folders + per-folder note lists.

    Node = {"folder", "children": [node...], "notes": [Note...]}.
    """
    nodes = {
        f.pk: {
            "folder": f,
            "children": [],
            "notes": notes_by_folder.get(f.pk, []),
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

    Every node renders collapsed; expansion state is per-browser-tab
    (sessionStorage), applied client-side by notes/tab-state.js — the
    server no longer tracks it, so tabs can't clobber each other's
    navigation. active_pane is only the fallback for tabs with no stored
    pane choice.
    """
    open_matters = list(Matter.objects.filter(status="Open").order_by("name"))
    if note.matter and note.matter not in open_matters:
        # Closed matter opened directly: surface it so the active pill exists
        open_matters.append(note.matter)
    matter_ids = {m.id for m in open_matters}

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
            ),
            "root_notes": notes_by_scope.get(m.id, {}).get(None, []),
        }
        for m in open_matters
    ]

    return {
        "file_tree": _build_tree(folders_by_matter.get(None, []), general),
        "root_notes": general.get(None, []),
        "matters": matters,
        "active_pane": "matters" if note.matter_id else "files",
        "recent_notes": [
            nv.note
            for nv in NoteView.objects.filter(user=request.user)
            .select_related("note", "note__matter")
            .order_by("-viewed_at")[:7]
        ],
    }


def _next_untitled(existing_names, base="Untitled"):
    """Obsidian-style auto-name: Untitled, then Untitled 1, 2, ..."""
    names = {n.lower() for n in existing_names}
    if base.lower() not in names:
        return base
    i = 1
    while f"{base.lower()} {i}" in names:
        i += 1
    return f"{base} {i}"


# Sibling-name uniqueness (the folder/file metaphor): checked at every
# rename/move mutation, case-insensitively — a filesystem export must
# not collide on macOS/Windows, which treat "Notes" and "notes" as the
# same file. View-layer enforcement (like the matter-boundary
# invariant): Postgres unique constraints treat the NULL folder/matter
# scopes as distinct rows, so they can't express these rules anyway.


def _sibling_note_exists(title, matter, folder, exclude_pk=None):
    qs = Note.objects.filter(matter=matter, folder=folder, title__iexact=title)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


def _sibling_folder_exists(name, matter, parent, exclude_pk=None):
    qs = NoteFolder.objects.filter(matter=matter, parent=parent, name__iexact=name)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.exists()


@login_required
@require_POST
def notes_add(request):
    """Create a general note instantly (no modal), optionally into a folder
    (?folder=<id>), auto-named among its siblings. The noteCreated
    trigger opens
    the new note in the editor.
    """
    folder = None
    folder_id = request.GET.get("folder", "")
    if folder_id.isdigit():
        folder = get_object_or_404(NoteFolder, pk=folder_id)
        if folder.matter_id is not None:
            return HttpResponse("Folder belongs to another matter.", status=400)

    siblings = Note.objects.filter(matter__isnull=True, folder=folder).values_list(
        "title", flat=True
    )
    note = Note.objects.create(
        title=_next_untitled(siblings),
        author=request.user,
        matter=None,
        folder=folder,
    )
    # No navigation: the client refreshes the trees in place and opens
    # the new note through the normal row-click swap (notes-editor.js)
    return HttpResponse(
        status=204,
        headers={"HX-Trigger": json.dumps({"noteCreated": {"id": note.id}})},
    )


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


# Headline sentinels: ts_headline marks matches, we escape the whole
# excerpt, then swap sentinels for <mark> — the HTML is safe by
# construction (never |safe on raw note content).
_HL_START, _HL_STOP = "\x02", "\x03"


def _safe_excerpt(raw):
    return mark_safe(
        escape(raw).replace(_HL_START, "<mark>").replace(_HL_STOP, "</mark>")
    )


def _palette_path(note):
    """Omnisearch-style path prefix for a palette row. A matter is the root
    directory of its notes' paths; library notes are rooted at the tree
    root, so a root library note has no prefix at all."""
    parts = []
    if note.matter_id:
        parts.append(note.matter.name)
    if note.folder:
        parts.extend(f.name for f in note.folder.get_ancestors() + [note.folder])
    return "/".join(parts)


def _parse_note_scope(user, scope_key, matter_qs=None):
    """Normalize a search scope key into (key, Note queryset, matter id set).

    scope_key: all (default) | library | matters | matter:<id>, 404 on a
    matter the user can't see. matter_qs bounds which matters count as
    accessible — the palette passes all of them, the JSON API open ones only.
    """
    if matter_qs is None:
        matter_qs = Matter.objects.all()
    accessible_matter_ids = set(
        filter_matters_for_user(matter_qs, user).values_list("id", flat=True)
    )
    if scope_key == "library":
        scope = Note.objects.filter(matter__isnull=True)
    elif scope_key == "matters":
        scope = Note.objects.filter(matter_id__in=accessible_matter_ids)
    elif scope_key.startswith("matter:") and scope_key[7:].isdigit():
        matter_id = int(scope_key[7:])
        if matter_id not in accessible_matter_ids:
            raise Http404
        scope = Note.objects.filter(matter_id=matter_id)
    else:
        scope_key = "all"
        scope = Note.objects.filter(
            Q(matter__isnull=True) | Q(matter_id__in=accessible_matter_ids)
        )
    return scope_key, scope, accessible_matter_ids


def _folder_path_index():
    """One folder sweep -> callable mapping a folder_id to its name path,
    root first. Cheaper than per-note get_ancestors() when annotating many
    notes at once."""
    folders = {f["id"]: f for f in NoteFolder.objects.values("id", "name", "parent_id")}

    def folder_path(folder_id):
        parts = []
        while folder_id:
            folder = folders.get(folder_id)
            if folder is None:
                break
            parts.append(folder["name"])
            folder_id = folder["parent_id"]
        return parts[::-1]

    return folder_path


def _palette_search(q, scope, title_limit=8, content_limit=10):
    """Two ranked result bands over scope for a query of length >= 2.

    Returns (title_notes, content_notes). The title band matches the query
    against each note's full display path (title-prefix hits rank above
    title-contains above path-only); the content band is watson full-text,
    each note carrying a raw .excerpt with \\x02/\\x03 headline sentinels.
    """
    # Paths aren't stored anywhere, so the title band matches in
    # memory: build each note's full display path from one folder
    # sweep and one values() pass over the scope (a few thousand rows
    # at most — cheap next to the round-trip)
    q_lower = q.lower()
    folder_path = _folder_path_index()

    ranked = []
    for row in scope.values("id", "title", "folder_id", "matter__name"):
        parts = []
        if row["matter__name"]:
            parts.append(row["matter__name"])
        parts.extend(folder_path(row["folder_id"]))
        parts.append(row["title"])
        if q_lower not in "/".join(parts).lower():
            continue
        title_lower = row["title"].lower()
        if title_lower.startswith(q_lower):
            rank = 0
        elif q_lower in title_lower:
            rank = 1
        else:
            rank = 2  # matched the path, not the title
        ranked.append((rank, title_lower, row["id"]))
    ranked.sort()
    title_ids = [note_id for _, _, note_id in ranked[:title_limit]]
    by_id = {
        n.id: n
        for n in Note.objects.filter(id__in=title_ids).select_related(
            "matter", "folder"
        )
    }
    title_notes = [by_id[note_id] for note_id in title_ids]

    sq = SearchQuery(q, search_type="websearch", config="english")
    content_notes = list(
        watson.filter(scope, q)
        .exclude(id__in=[n.id for n in title_notes])
        .order_by("-watson_rank")
        .annotate(
            excerpt=SearchHeadline(
                "content",
                sq,
                config="english",
                start_sel=_HL_START,
                stop_sel=_HL_STOP,
                max_words=18,
                min_words=10,
            )
        )
        .select_related("matter", "folder")[:content_limit]
    )
    return title_notes, content_notes


@login_required
def notes_search_palette(request):
    """The editor's Ctrl+K search palette (Omnisearch-style).

    GET renders the whole modal with the Recent band; the input's debounced
    hx-post comes back here and gets just the results partial. Two ranked
    bands: path matches (the query is checked against each note's full
    display path — matter/folders/title — with title hits ranked above
    path-only hits), then full-text matches via watson with a
    match-centered highlighted excerpt.

    ?scope= narrows both bands and the recents: all (default) | library |
    matters | matter:<id>. The GET also takes ?note=<open note> so the
    shell can offer that note's matter as a one-click scope tab.
    """
    q = (request.POST.get("q") or request.GET.get("q") or "").strip()
    scope_key = request.POST.get("scope") or request.GET.get("scope") or "all"
    scope_key, scope, accessible_matter_ids = _parse_note_scope(request.user, scope_key)

    # The open note's matter feeds the shell's one-click scope tab
    current_matter = None
    note_id = request.GET.get("note", "")
    if request.method == "GET" and note_id.isdigit():
        current = Note.objects.select_related("matter").filter(pk=note_id).first()
        if current and current.matter_id in accessible_matter_ids:
            current_matter = current.matter

    title_notes, content_notes, recent_notes = [], [], []
    if len(q) < 2:
        scoped_note_ids = set(scope.values_list("id", flat=True))
        recent_notes = [
            nv.note
            for nv in NoteView.objects.filter(user=request.user)
            .select_related("note__matter", "note__folder")
            .order_by("-viewed_at")[:30]
            if nv.note_id in scoped_note_ids
        ][:10]
    else:
        title_notes, content_notes = _palette_search(q, scope)

    for n in title_notes + content_notes + recent_notes:
        n.path_prefix = _palette_path(n)
    for n in content_notes:
        n.safe_excerpt = _safe_excerpt(n.excerpt)

    template = (
        "notes/palette-results.html"
        if request.method == "POST"
        else "notes/palette.html"
    )
    context = {
        "q": q,
        "scope": scope_key,
        "current_matter": current_matter,
        "title_notes": title_notes,
        "content_notes": content_notes,
        "recent_notes": recent_notes,
    }
    return render(request, template, context)


@login_required
def notes_launch(request):
    """Open the editor at the user's most recently viewed note.

    The sidebar's Notes launcher points here. Falls back to the latest
    note the user can reach, and finally creates a fresh untitled note so
    the editor always has something to open.
    """
    nv = (
        NoteView.objects.filter(user=request.user)
        .select_related("note")
        .order_by("-viewed_at")
        .first()
    )
    note = nv.note if nv else None
    if note is None:
        accessible = filter_matters_for_user(Matter.objects.all(), request.user)
        note = (
            Note.objects.filter(Q(matter__isnull=True) | Q(matter__in=accessible))
            .order_by("-updated_at")
            .first()
        )
    if note is None:
        note = Note.objects.create(title="Untitled", author=request.user, matter=None)
    return redirect("notes:note-view", note.id)


def _get_note(request, note_id, **filters):
    """Fetch a note for a per-note endpoint: general notes are shared,
    matter notes require access to their matter (404 either way, so denial
    doesn't confirm existence). Every /notes/<id>/... view goes through
    here — the routes serve both kinds of note."""
    note = get_object_or_404(
        Note.objects.select_related("matter"), pk=note_id, **filters
    )
    if note.matter_id and not request.user.has_matter_access(note.matter):
        raise Http404
    return note


@login_required
def note_view(request, note_id):
    """Standalone editor view for a note."""
    note = _get_note(request, note_id)

    # Record user's view of this note
    record_note_view(request.user, note)

    context = {"note": note, "matter": note.matter} | get_editor_file_tree(
        request, note
    )
    return render(request, "notes/editor.html", context)


@login_required
def note_content_partial(request, note_id):
    """HTMX partial for switching notes in the editor.

    ?sync=1 marks a background reload (another tab saved this note) —
    those must not count as the user viewing the note, or every silent
    sync would reorder recents and hijack notes:launch.
    """
    note = _get_note(request, note_id)

    if not request.GET.get("sync"):
        record_note_view(request.user, note)

    context = {
        "note": note,
        "matter": note.matter,
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
    note = _get_note(request, note_id)
    context = {"note": note} | get_editor_file_tree(request, note)
    return render(request, "notes/editor-trees.html", context)


AI_WRITE_HOURS = 24


@login_required
@require_POST
def note_ai_write(request, note_id):
    """Toggle the note's AI-write grant (Claude Desktop MCP writes).

    On grants access for AI_WRITE_HOURS from now; off (or an expired
    grant) clears/renews it. Saved with update_fields so updated_at stays
    put: a bump here would make an open editor's autosave base_version
    look stale and raise a spurious conflict banner.
    """
    note = _get_note(request, note_id)
    if note.ai_write_until and note.ai_write_until > timezone.now():
        note.ai_write_until = None
    else:
        note.ai_write_until = timezone.now() + timedelta(hours=AI_WRITE_HOURS)
    note.save(update_fields=["ai_write_until"])
    return JsonResponse(
        {
            "ai_write_until": (
                note.ai_write_until.isoformat() if note.ai_write_until else None
            )
        }
    )


@login_required
@require_POST
def note_delete(request, note_id):
    """Delete a note."""
    note = _get_note(request, note_id)
    note.delete()

    return HttpResponse(status=204, headers={"HX-Trigger": "notesChanged"})


@login_required
def note_content(request, note_id):
    """GET returns markdown content, POST saves it."""
    note = _get_note(request, note_id)

    if request.method == "POST":
        content = request.POST.get("content", "")
        note.content = content
        note.save()
        if note.matter_id is None:
            queue_note_summary(note.id)
        return HttpResponse(status=204)

    return HttpResponse(note.content, content_type="text/plain; charset=utf-8")


def _version_conflict(request, note):
    """409 when the client's note is stale (edited from another tab).

    The client echoes back the exact updated_at isoformat string it last
    received (base_version); any difference means someone else saved
    since. Optional: callers that don't send it save unconditionally.
    """
    base_version = request.POST.get("base_version", "")
    if base_version and base_version != note.updated_at.isoformat():
        return JsonResponse(
            {
                "saved": False,
                "conflict": True,
                "updated_at": note.updated_at.isoformat(),
            },
            status=409,
        )
    return None


@login_required
@require_POST
def note_autosave(request, note_id):
    """Autosave endpoint for the editor."""
    note = _get_note(request, note_id)

    conflict = _version_conflict(request, note)
    if conflict:
        return conflict

    content = request.POST.get("content", "")
    note.content = content
    # updated_by is set by AuditMixin.save; include it in update_fields so the
    # change is actually persisted.
    note.save(update_fields=["content", "updated_at", "updated_by"])
    # Library notes carry AI summaries for the selector manifest; matter
    # notes feed their matter's context directly
    if note.matter_id is None:
        queue_note_summary(note.id)

    return JsonResponse({"saved": True, "updated_at": note.updated_at.isoformat()})


@login_required
@require_POST
def note_title(request, note_id):
    """Update note title."""
    note = _get_note(request, note_id)

    conflict = _version_conflict(request, note)
    if conflict:
        return conflict

    title = request.POST.get("title", "").strip()
    if title and _sibling_note_exists(title, note.matter, note.folder, note.pk):
        return JsonResponse(
            {"saved": False, "error": f'A note named "{title}" already exists here.'},
            status=400,
        )
    if title:
        note.title = title
        note.save(update_fields=["title", "updated_at", "updated_by"])
        return JsonResponse(
            {
                "saved": True,
                "title": note.title,
                "updated_at": note.updated_at.isoformat(),
            }
        )

    return JsonResponse({"saved": False, "error": "Title cannot be empty"}, status=400)


@login_required
def note_meta(request, note_id):
    """Render the note meta partial (used by HTMX to refresh after autosave)."""
    note = _get_note(request, note_id)
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
    """Search the note's matter for documents and highlights to reference.
    Library notes have no matter, so they get empty results."""
    from apps.case.models import Document, Highlight

    note = _get_note(request, note_id)
    matter = note.matter
    query = request.GET.get("q", "").strip()

    documents = []
    highlights = []

    if query and matter:
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
    from apps.case.models import Document, Highlight

    doc_ids = request.GET.getlist("doc")
    hl_ids = request.GET.getlist("hl")

    citations = {}

    for doc in Document.objects.filter(id__in=doc_ids):
        citations[f"doc:{doc.id}"] = doc.citation

    for hl in Highlight.objects.filter(id__in=hl_ids).select_related("document"):
        citations[f"hl:{hl.id}"] = hl.citation

    return JsonResponse(citations)


@login_required
def note_properties(request, note_id):
    """Properties modal for a matter note (matter re-assignment)."""
    note = _get_note(request, note_id, matter__isnull=False)
    matters = filter_matters_for_user(
        Matter.objects.filter(status="Open").order_by("name"), request.user
    )
    context = {"note": note, "matters": matters}
    return render(request, "notes/properties-modal.html", context)


@login_required
@require_POST
def note_reassign_matter(request, note_id):
    """Move a matter note to another matter; folder resets to that matter's
    root (a folder always belongs to exactly one matter's tree)."""
    note = _get_note(request, note_id, matter__isnull=False)
    matter = get_object_or_404(
        filter_matters_for_user(Matter.objects.filter(status="Open"), request.user),
        pk=request.POST.get("matter"),
    )
    if matter.id != note.matter_id:
        note.matter = matter
        note.folder = None
        update_fields = ["matter", "folder"]
        # Same-named note at the target root → serial suffix, like a
        # filesystem move
        siblings = Note.objects.filter(matter=matter, folder=None).values_list(
            "title", flat=True
        )
        suffixed = _next_untitled(siblings, base=note.title)
        if suffixed != note.title:
            note.title = suffixed
            update_fields += ["title", "updated_at", "updated_by"]
        note.save(update_fields=update_fields)
    return HttpResponse(
        status=204,
        headers={
            "HX-Trigger": json.dumps({"noteFoldersChanged": True, "closeModal": True})
        },
    )


# ---------------------------------------------------------------------------
# Note Folder views
# ---------------------------------------------------------------------------


def _editor_crud_response():
    """Editor-context success: refresh the trees and close the modal."""
    return HttpResponse(
        status=204,
        headers={
            "HX-Trigger": json.dumps({"noteFoldersChanged": True, "closeModal": True})
        },
    )


@login_required
@require_POST
def note_folder_add(request):
    """Create a folder instantly (no modal), auto-named among its siblings.

    ?parent=<id> creates a subfolder (matter inherited from the parent);
    ?matter=<id> creates at a matter's root; neither means the general
    root. The folderCreated trigger starts an Obsidian-style inline
    rename on the new row once the refreshed tree settles.
    """
    parent_id = request.GET.get("parent", "")
    matter_id = request.GET.get("matter", "")
    parent = matter = None
    if parent_id.isdigit():
        parent = get_object_or_404(NoteFolder, pk=parent_id)
        matter = parent.matter
        if not parent.can_have_children():
            return HttpResponse("Maximum folder depth (4 levels) exceeded.", status=400)
    elif matter_id.isdigit():
        matter = get_object_or_404(Matter, pk=matter_id)

    siblings = NoteFolder.objects.filter(parent=parent, matter=matter).values_list(
        "name", flat=True
    )
    folder = NoteFolder.objects.create(
        name=_next_untitled(siblings), parent=parent, matter=matter
    )
    # Key order matters: noteFoldersChanged's handler starts the tree
    # refresh; folderCreated's then waits on that swap to settle
    return HttpResponse(
        status=204,
        headers={
            "HX-Trigger": json.dumps(
                {"noteFoldersChanged": True, "folderCreated": {"id": folder.id}}
            )
        },
    )


@login_required
@require_POST
def note_folder_rename(request, folder_id):
    """Name-only update (the tree's inline rename); parent/matter untouched."""
    folder = get_object_or_404(NoteFolder, pk=folder_id)
    name = request.POST.get("name", "").strip()
    if not name:
        return HttpResponse("Name cannot be empty.", status=400)
    if _sibling_folder_exists(name, folder.matter, folder.parent, folder.pk):
        return HttpResponse(f'A folder named "{name}" already exists here.', status=400)
    folder.name = name
    folder.save(update_fields=["name"])
    return _editor_crud_response()


@login_required
def note_folder_edit(request, folder_id):
    """Edit a note folder (editor modal)."""
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
            return _editor_crud_response()
    else:
        form = NoteFolderForm(instance=folder, exclude_folder=folder)

    query = request.GET.urlencode()
    context = {
        "form": form,
        "action": f"/notes/folders/edit/{folder_id}" + (f"?{query}" if query else ""),
        "edit": True,
        "folder": folder,
        "editor_context": True,
        "extra_qs": query,
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

    folder.delete()

    # Editor context: if the open note went down with the folder, a plain
    # refresh would 404 — send the user to the notes index instead.
    note_id = request.GET.get("note", "")
    if (
        request.GET.get("context") == "editor"
        and note_id.isdigit()
        and not Note.objects.filter(pk=note_id).exists()
    ):
        return HttpResponse(
            status=204, headers={"HX-Redirect": reverse("notes:launch")}
        )

    # Refresh the trees in place (a full HX-Refresh reload would dump the
    # panel's scroll position and any open editing state)
    return _editor_crud_response()


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
    update_fields = ["parent", "depth"]
    # Same-named sibling at the destination → serial suffix, like a
    # filesystem move
    siblings = (
        NoteFolder.objects.filter(matter=folder.matter, parent=destination)
        .exclude(pk=folder.pk)
        .values_list("name", flat=True)
    )
    suffixed = _next_untitled(siblings, base=folder.name)
    if suffixed != folder.name:
        folder.name = suffixed
        update_fields.append("name")
    folder.save(update_fields=update_fields)
    folder.update_descendant_depths()
    return HttpResponse(status=204)


@login_required
@require_POST
def note_move(request, note_id):
    """Move a note to a different folder (editor drag-and-drop).

    Serves general AND matter notes; the destination must live in the
    note's own tree. note.matter is never written here.
    """
    note = get_object_or_404(Note, pk=note_id)

    folder_id = request.POST.get("destination")
    if folder_id:
        folder = get_object_or_404(NoteFolder, pk=folder_id)
        if folder.matter_id != note.matter_id:
            return HttpResponse(
                "Notes cannot move into another matter's folders.", status=400
            )
        destination = folder
    else:
        destination = None
    note.folder = destination
    update_fields = ["folder"]
    # A same-named sibling at the destination gets a serial suffix
    # (filesystem move behavior) rather than blocking the move
    siblings = (
        Note.objects.filter(matter=note.matter, folder=destination)
        .exclude(pk=note.pk)
        .values_list("title", flat=True)
    )
    suffixed = _next_untitled(siblings, base=note.title)
    if suffixed != note.title:
        note.title = suffixed
        update_fields += ["title", "updated_at", "updated_by"]
    note.save(update_fields=update_fields)
    return HttpResponse(status=204, headers={"HX-Trigger": "notesChanged"})
