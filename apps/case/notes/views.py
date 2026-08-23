import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.case.views import get_matter_from_url, get_session_key, set_last_tab
from apps.notes.models import Note, NoteFolder
from apps.notes.views import IMPORTANCE_LABELS, _next_untitled, _sibling_note_exists

from .filters import NotesFilter
from .forms import NoteForm

NOTES_TRIGGER = "notesChanged"


def _filter_key(matter_id):
    return get_session_key("notes_filter", matter_id)


def get_notes_data(request, matter, matter_id):
    """The matter's notes with the session filters applied (no pagination or
    selection, like the witnesses and facts tabs)."""
    filter_data = request.session.get(_filter_key(matter_id), {})

    notes = []
    if matter:
        queryset = Note.objects.filter(matter=matter).order_by("-updated_at")
        if filter_data:
            notes = NotesFilter(filter_data, queryset=queryset, matter=matter).qs
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
    selected_category = dict(Note.CATEGORY_CHOICES).get(category_key, "")

    selected_topic = filter_data.get("topic", "")
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
        "selected_importance": IMPORTANCE_LABELS.get(importance_value, ""),
        "category_choices": Note.CATEGORY_CHOICES,
        "selected_category": selected_category,
        "selected_category_key": category_key,
        "topics": topics,
        "selected_topic": selected_topic,
    }


@login_required
def notes_index(request, matter_id):
    """The case Notes sub-tab."""
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
    """HTMX partial for the sub-tab (toolbar + table)."""
    matter, matters = get_matter_from_url(request, matter_id)

    context = {
        "app": "matters",
        "subapp": "notes",
        "matter": matter,
        "matters": matters,
    } | get_notes_data(request, matter, matter_id)
    return render(request, "case/notes/list.html", context)


@login_required
@require_POST
def notes_add(request, matter_id):
    """Create a matter note instantly (no modal), optionally into one of the
    matter's folders (?folder=<id>), auto-named among its siblings.

    Editor: the noteCreated trigger opens the new note in place (no
    navigation). Notes sub-tab: ?open=1 (a plain form post into a new tab)
    redirects straight to the editor instead.
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
    if request.GET.get("open"):
        return redirect("notes:note-view", note.id)
    return HttpResponse(
        status=204,
        headers={"HX-Trigger": json.dumps({"noteCreated": {"id": note.id}})},
    )


@login_required
def note_edit(request, note_id):
    """Edit Details modal (matter, category, title) from the table row."""
    note = get_object_or_404(Note.objects.select_related("matter"), pk=note_id)
    matter = note.matter
    if matter is None or not request.user.has_matter_access(matter):
        return HttpResponse(status=404)

    if request.method == "POST":
        form = NoteForm(
            request.POST, instance=note, user=request.user, use_required_attribute=False
        )
        if form.is_valid():
            new_matter = form.cleaned_data["matter"]
            title = form.cleaned_data["title"].strip()
            # A matter change returns the note to that matter's root (folders
            # belong to exactly one matter's tree); the title stays unique
            # among its new siblings
            folder = note.folder if new_matter.id == matter.id else None
            if _sibling_note_exists(title, new_matter, folder, note.pk):
                form.add_error(
                    "title", f'A note named "{title}" already exists in this folder.'
                )
            else:
                note = form.save(commit=False)
                note.folder = folder
                note.save()
                return HttpResponse(status=204, headers={"HX-Trigger": NOTES_TRIGGER})
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


def _update_filter(request, matter_id, **changes):
    """Merge keys into the matter's session filter dict; None pops the key."""
    key = _filter_key(matter_id)
    filter_data = request.session.get(key, {})
    for name, value in changes.items():
        if value is None:
            filter_data.pop(name, None)
        else:
            filter_data[name] = value
    request.session[key] = filter_data
    request.session.modified = True
    return filter_data


@login_required
def notes_filter(request, matter_id):
    """Filter modal; POST stores the whole form in the session."""
    matter, matters = get_matter_from_url(request, matter_id)
    key = _filter_key(matter_id)

    if request.method == "POST":
        request.session[key] = {
            k: v for k, v in request.POST.items() if k != "csrfmiddlewaretoken"
        }
        request.session.modified = True
        return HttpResponse(status=204, headers={"HX-Trigger": NOTES_TRIGGER})

    filter_data = request.session.get(key, {})
    queryset = Note.objects.filter(matter=matter) if matter else Note.objects.none()
    filter_obj = NotesFilter(filter_data, queryset=queryset, matter=matter)
    return render(
        request, "case/notes/filter.html", {"filter": filter_obj, "matter": matter}
    )


@login_required
def notes_sort(request, matter_id, order):
    """Column sort; a second click on the same column flips direction."""
    filter_data = request.session.get(_filter_key(matter_id), {})
    current_order = filter_data.get("order_by", "")
    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order
    _update_filter(request, matter_id, order_by=new_order)
    return redirect("case:notes-list", matter_id=matter_id)


@login_required
def notes_filter_keyword(request, matter_id):
    """Live keyword search (title or content) from the toolbar input."""
    matter, _ = get_matter_from_url(request, matter_id)
    keyword = request.GET.get("keyword", "").strip()
    _update_filter(request, matter_id, keyword=keyword or None)
    context = {"matter": matter} | get_notes_data(request, matter, matter_id)
    return render(request, "case/notes/table.html", context)


@login_required
def notes_filter_importance(request, matter_id, importance_value):
    """Importance-at-least filter; 0 clears it."""
    _update_filter(
        request, matter_id, importance="" if importance_value == 0 else importance_value
    )
    return redirect("case:notes-list", matter_id=matter_id)


@login_required
def notes_filter_category(request, matter_id, category):
    _update_filter(request, matter_id, category=category or None)
    return redirect("case:notes-list", matter_id=matter_id)


@login_required
def notes_filter_topic(request, matter_id, topic):
    _update_filter(request, matter_id, topic=topic or None)
    return redirect("case:notes-list", matter_id=matter_id)


@login_required
def notes_filter_topic_clear(request, matter_id):
    _update_filter(request, matter_id, topic=None)
    return redirect("case:notes-list", matter_id=matter_id)


@login_required
@require_POST
def note_category(request, note_id, value):
    """Inline category change from the table row."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=False)
    note.category = value
    note.save(update_fields=["category"])
    return redirect("case:notes-list", matter_id=note.matter_id)


@login_required
@require_POST
def note_importance(request, note_id, value):
    """Inline importance change from the table row."""
    note = get_object_or_404(Note, pk=note_id, matter__isnull=False)
    note.importance = value
    note.save(update_fields=["importance"])
    return redirect("case:notes-list", matter_id=note.matter_id)
