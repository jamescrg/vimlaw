"""Translation of raw context handles the AI leaks into its output.

Context items carry [doc:ID], [hl:ID], and [note:ID] handles so the AI can
cite and target them (SOURCE_LINKING teaches markdown links; the write
protocols consume ids). Models still sometimes emit the raw handles in
prose, which are meaningless to a human. These helpers are the safety
net, applied after the response arrives:

- resolve_handles_for_chat(): handle -> markdown link (same targets
  SOURCE_LINKING teaches), so the chat message reads and clicks.
- resolve_handles_for_note(): handle -> the notes' native reference-chip
  syntax ([[doc:ID|label]] / [[hl:ID|label]]), so an AI-written note gets
  real chips; [note:ID] becomes the note's title as plain text.

Out-of-scope or nonexistent ids are omitted entirely — a hallucinated
handle must not become a link.
"""

import re

from django.db.models import Q

from apps.case.models import Document, Highlight
from apps.notes.models import Note, library_folder_ids

HANDLE_RE = re.compile(r"\[(doc|hl|note):(\d+)\]")


def _clean_label(text, fallback):
    """Strip the characters that would break markdown links or chip syntax."""
    label = re.sub(r"[\[\]|]", "", str(text or "")).replace("\n", " ").strip()
    return label[:80] or fallback


def _resolve(kind, item_id, matter):
    """Return (label, url) for an in-scope handle, or None."""
    if kind == "doc":
        doc = Document.objects.filter(id=item_id, matter=matter).first()
        if doc:
            return (
                _clean_label(doc.name, f"Document {doc.id}"),
                f"/case/documents/{doc.id}/view/",
            )
    elif kind == "hl":
        hl = (
            Highlight.objects.filter(id=item_id)
            .filter(Q(document__matter=matter) | Q(caselaw__matter=matter))
            .first()
        )
        if hl:
            return (
                _clean_label(hl.citation, f"Highlight {hl.id}"),
                f"/case/highlights/{hl.id}/link/",
            )
    elif kind == "note":
        note = Note.objects.filter(id=item_id).first()
        if note and note.matter_id == matter.id:
            return (
                _clean_label(note.title, f"Note {note.id}"),
                f"/case/notes/{note.id}/",
            )
        if note and note.matter_id is None and note.folder_id in library_folder_ids():
            return (_clean_label(note.title, f"Note {note.id}"), f"/notes/{note.id}/")
    return None


def resolve_handles_for_chat(text, matter):
    """Replace raw handles with markdown links; omit unresolvable ones."""

    def sub(match):
        resolved = _resolve(match.group(1), int(match.group(2)), matter)
        if resolved is None:
            return ""
        label, url = resolved
        return f"[{label}]({url})"

    return HANDLE_RE.sub(sub, text)


def resolve_handles_for_note(text, matter):
    """Replace raw handles with note reference chips ([[doc:ID|label]] /
    [[hl:ID|label]]); [note:ID] becomes the title; omit unresolvable ones."""

    def sub(match):
        kind, item_id = match.group(1), int(match.group(2))
        resolved = _resolve(kind, item_id, matter)
        if resolved is None:
            return ""
        label, _url = resolved
        if kind in ("doc", "hl"):
            return f"[[{kind}:{item_id}|{label}]]"
        return label

    return HANDLE_RE.sub(sub, text)
