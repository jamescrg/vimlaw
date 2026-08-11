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
from apps.notes.models import Note

HANDLE_RE = re.compile(r"\[(doc|hl|note):(\d+)\]")

# SOURCE_LINKING-style markdown citations. The notes protocol says to use
# raw handles in note content, but a model steeped in the chat convention
# will still write these — convert them too rather than leaving dead
# markdown in a note.
MD_SOURCE_LINK_RE = re.compile(
    r"\[([^\]]+)\]\(/case/(documents|highlights)/(\d+)/(?:view|link)/\)"
)

# Invented handle-style citations to records that are not citable
# (observed live: "[fact:2026-03-17]"). Only documents and highlights
# are citation targets; these are stripped along with any space before
# them. The colon requirement keeps ordinary bracketed prose ("[Fact
# Sheet]") safe.
PSEUDO_HANDLE_RE = re.compile(
    r"\s*\[(?:facts?|tasks?|events?|time|entry|entries|conv|conversations?|emails?)"
    r":[^\]]*\]",
    re.IGNORECASE,
)


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
        if note and note.matter_id is None:
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

    text = PSEUDO_HANDLE_RE.sub("", text)
    return HANDLE_RE.sub(sub, text)


def resolve_handles_for_note(text, matter):
    """Replace raw handles with note reference chips ([[doc:ID|label]] /
    [[hl:ID|label]]); [note:ID] becomes the title; omit unresolvable ones.
    Chat-style markdown source links become chips as well, keeping the
    model's own citation text as the chip label."""

    def sub_md_link(match):
        label_text, path_kind, item_id = match.groups()
        kind = "doc" if path_kind == "documents" else "hl"
        if _resolve(kind, int(item_id), matter) is None:
            return ""
        label = _clean_label(label_text, f"{kind}:{item_id}")
        return f"[[{kind}:{item_id}|{label}]]"

    def sub_handle(match):
        kind, item_id = match.group(1), int(match.group(2))
        resolved = _resolve(kind, item_id, matter)
        if resolved is None:
            return ""
        label, _url = resolved
        if kind in ("doc", "hl"):
            return f"[[{kind}:{item_id}|{label}]]"
        return label

    text = PSEUDO_HANDLE_RE.sub("", text)
    text = MD_SOURCE_LINK_RE.sub(sub_md_link, text)
    return HANDLE_RE.sub(sub_handle, text)
