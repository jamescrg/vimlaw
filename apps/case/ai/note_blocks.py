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
chat reply.

When a sentence in note content draws on a document or highlight from
the context, cite it with the raw [hl:ID] or [doc:ID] handle, placed
after the sentence's closing period ("Service was defective under the
statute. [hl:88]"). Each handle becomes a clickable source chip in the
note. Do not use markdown links inside note content. Documents and
highlights are the ONLY citable sources in a note — never cite tasks,
time entries, timeline facts, events, or other case records.

Confirmation lines like "- Created note: **X**" in earlier assistant
turns are SYSTEM-GENERATED records of writes that already happened —
they are not something you write. A note is written only by emitting
the fenced block; writing a confirmation-style line yourself does
nothing and is treated as an error."""


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
    firm-library notes — never AI-hidden ones. (Drive-imported notes are
    app-owned since the sync retired and are editable like any other.)"""
    try:
        note = Note.objects.get(id=int(note_id))
    except (Note.DoesNotExist, TypeError, ValueError):
        return None

    in_matter = note.matter_id == matter.id
    in_library = note.matter_id is None and note.folder_id in library_folder_ids()
    if not (in_matter or in_library):
        return None
    if note.ai_context == "never":
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


# A model that has seen real confirmations in its history sometimes
# imitates the line instead of emitting the block — a fake success with no
# write behind it (observed live: "Created note: **Matter Summary 3**"
# with no block). Runs on the RAW response, before block replacement, so
# it can only ever match model-written lines; the real confirmations are
# substituted afterwards. The optional leading [..] absorbs an imitated
# history timestamp.
FAKE_CONFIRMATION_RE = re.compile(
    r"^[ \t]*(?:\[[^\]\n]*\][ \t]*)?-?[ \t]*"
    r"(?:Created|Appended to|Rewrote) (?:library )?note:.*$",
    re.MULTILINE,
)

FAKE_CONFIRMATION_NOTICE = (
    "*(The assistant described a note write without performing one — "
    "no note was changed. Ask again to retry.)*"
)


def strip_fake_note_confirmations(response_text):
    """Neutralize model-written confirmation lookalikes.

    Must run before apply_note_blocks: at that point any line matching the
    confirmation format was written by the model, not by us. Lines inside
    fenced blocks cannot match — block payloads are single-line JSON.

    When the response also carries a real write block, the imitation is
    simply deleted (the genuine confirmation will replace the block);
    with no block anywhere, it becomes an honest "nothing happened"
    notice instead of a fake success.
    """
    replacement = (
        "" if NOTE_BLOCKS_RE.search(response_text) else (FAKE_CONFIRMATION_NOTICE)
    )
    return FAKE_CONFIRMATION_RE.sub(replacement, response_text)


def apply_note_blocks(response_text, matter, requesting_user):
    """Create and edit Notes from any note blocks, replacing each block
    with a confirmation line. A malformed block is left as text and
    writes nothing."""
    response_text = CREATE_NOTE_RE.sub(
        lambda m: _apply_create(m, matter, requesting_user), response_text
    )
    return EDIT_NOTE_RE.sub(lambda m: _apply_edit(m, matter), response_text)
