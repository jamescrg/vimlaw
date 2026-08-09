"""Note creation and editing from case AI chat.

The classic-path case chat worker appends NOTES_PROTOCOL to its system
context (when the recent user messages point at note work) and runs
apply_note_blocks() over the response. The AI proposes writes in
```create-note``` / ```edit-note``` fenced blocks; each block is replaced
in the stored message with a confirmation line, so both the user and the
AI's later turns see what happened. A malformed block is left as text and
writes nothing (same contract as create-facts).

Guardrails: creation is limited to this matter's notes; edits reach this
matter's notes plus firm-library notes (the ones the AI can already
read), and never Drive-synced or ai_context="never" notes. Every content
change lands in the note's HistoricalRecords trail, so a bad AI edit is
recoverable.
"""

import json
import logging
import re

from apps.notes.models import Note, library_folder_ids

from .handles import resolve_handles_for_note

logger = logging.getLogger(__name__)

CREATE_NOTE_RE = re.compile(r"```create-note\s*\n(.*?)```", re.DOTALL)
EDIT_NOTE_RE = re.compile(r"```edit-note\s*\n(.*?)```", re.DOTALL)
NOTE_BLOCKS_RE = re.compile(r"```(?:create|edit)-note\s*\n", re.DOTALL)

# Recent-user-message words that make the notes protocol relevant
# (tasks.py withholds it otherwise, so ordinary chats carry no standing
# write instructions to misfire on).
NOTES_TRIGGER_RE = re.compile(r"\bnotes?\b|\blibrary\b|\bmemo", re.IGNORECASE)

VALID_CATEGORIES = {value for value, _ in Note.CATEGORY_CHOICES}

NOTES_PROTOCOL = """WRITING TO NOTES. This matter's notes and the firm-library notes in the
context above carry [note:ID] handles. Only when the user explicitly
directs you to write to a note ("save this to a note", "write your
conclusion to a note", "update the library note on service of process")
end your reply with fenced blocks in these forms.

To create a new note on this matter:

```create-note
{"title": "<up to 200 chars>", "category": "analysis", "topic": null, "content": "<markdown>"}
```

To change an existing note by its [note:ID] handle:

```edit-note
{"id": 123, "mode": "append", "content": "<markdown>"}
```

Being asked to analyze, summarize, or conclude is a request for PROSE in
your reply, not direction to write a note: answer in ordinary text and
do not emit a block. Never emit a block unprompted; when unsure whether
the user wants a note written, answer in prose and ask.

Give your full answer in prose first — the block is replaced with a
short confirmation, so anything only inside it is invisible in the chat.
"category" is one of: analysis, drafting, guide, interview, issue, note,
research. "mode" is "append" (add your text after the existing content —
the default, and almost always right) or "replace" (rewrite the whole
note — only when the user explicitly says to rewrite or replace it).
Edit only notes whose [note:ID] handle appears in the context; never
guess an id. Notes synced from Google Drive are read-only and cannot be
edited. Content is markdown; write it as a working file memo, not as a
chat reply."""


def _apply_create(match, matter, requesting_user):
    try:
        entry = json.loads(match.group(1).strip())
        if not isinstance(entry, dict):
            raise ValueError("create-note block is not an object")
    except (ValueError, TypeError):
        logger.warning("Unparseable create-note block left in place")
        return match.group(0)

    title = str(entry.get("title") or "").strip()[:200]
    content = str(entry.get("content") or "").strip()
    if len(title) < 3 or not content:
        return match.group(0)
    # Raw [doc:]/[hl:] handles become the note's native reference chips
    content = resolve_handles_for_note(content, matter)

    category = str(entry.get("category") or "note").strip().lower()
    if category not in VALID_CATEGORIES:
        category = "note"
    topic = str(entry.get("topic") or "").strip()[:255] or None

    note = Note.objects.create(
        matter=matter,
        author=requesting_user,
        title=title,
        category=category,
        topic=topic,
        content=content,
    )
    return f"- Created note: **{note.title}** [{note.get_category_display()}]"


def _editable_note(note_id, matter):
    """Resolve an edit target the AI may touch: this matter's notes or
    firm-library notes — never synced or AI-hidden ones."""
    try:
        note = Note.objects.get(id=int(note_id))
    except (Note.DoesNotExist, TypeError, ValueError):
        return None

    in_matter = note.matter_id == matter.id
    in_library = note.matter_id is None and note.folder_id in library_folder_ids()
    if not (in_matter or in_library):
        return None
    if note.drive_file_id or note.ai_context == "never":
        return None
    return note


def _apply_edit(match, matter):
    try:
        entry = json.loads(match.group(1).strip())
        if not isinstance(entry, dict):
            raise ValueError("edit-note block is not an object")
    except (ValueError, TypeError):
        logger.warning("Unparseable edit-note block left in place")
        return match.group(0)

    content = str(entry.get("content") or "").strip()
    if not content:
        return match.group(0)
    content = resolve_handles_for_note(content, matter)

    note = _editable_note(entry.get("id"), matter)
    if note is None:
        return f"(note {entry.get('id')} not found or not editable)"

    mode = str(entry.get("mode") or "append").strip().lower()
    if mode == "replace":
        note.content = content
        verb = "Rewrote"
    else:
        note.content = (note.content.rstrip() + "\n\n" + content).strip()
        verb = "Appended to"
    note.save()

    scope = "library note" if note.matter_id is None else "note"
    return f"- {verb} {scope}: **{note.title}**"


def apply_note_blocks(response_text, matter, requesting_user):
    """Create and edit Notes from any note blocks, replacing each block
    with a confirmation line. A malformed block is left as text and
    writes nothing."""
    response_text = CREATE_NOTE_RE.sub(
        lambda m: _apply_create(m, matter, requesting_user), response_text
    )
    return EDIT_NOTE_RE.sub(lambda m: _apply_edit(m, matter), response_text)
