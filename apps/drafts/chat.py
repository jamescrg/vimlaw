"""Draft editing inside case AI chat.

When a conversation has a DraftLink, the case chat worker appends
build_draft_section() to its system context and runs apply_edit_blocks()
over the response. The AI proposes changes in a ```draft-edits``` fenced
block; each block is replaced in the stored message with the outcome text,
so both the user and the AI's later turns see what happened.

Application is companion-only: a connected LibreOffice companion receives
the round and applies it to the live document as tracked changes; with no
companion connected the block is refused with instructions, and the
document is untouched. There is no server-side fallback, because there is
no server-side working copy.
"""

import json
import logging
import re
import time

from apps.drafts.models import CompanionRound
from apps.drive.redline import (
    DeleteParagraph,
    InsertParagraphs,
    RedlineEdit,
    edit_to_dict,
)

logger = logging.getLogger(__name__)

DRAFT_EDITS_RE = re.compile(r"```draft-edits\s*\n(.*?)```", re.DOTALL)

# How long the worker waits for a connected companion to apply a round. The
# extension polls every ~2.5 s and application itself is sub-second, so a
# healthy companion answers well inside this.
COMPANION_WAIT_SECONDS = 30

DRAFT_PREAMBLE = """A DRAFT DOCUMENT is linked to this conversation (a work in progress,
not a filed or executed instrument). The attorney has it open in
LibreOffice Writer; help improve it: discuss structure and substance,
weigh alternative language, and propose concrete edits when directed.
The draft's current text follows below as a plain-text facsimile of the
word-processor file, refreshed as the attorney works."""

EDIT_PROTOCOL = """PROPOSING EDITS. Only when the user directs you to change the draft, end
your reply with exactly one fenced block containing a JSON list of
operations, applied in order:

```draft-edits
[{"old": "<exact text now in the draft>", "new": "<replacement text>", "replace_all": false},
 {"op": "delete_paragraph", "text": "<text identifying the paragraph>"},
 {"op": "insert_after", "anchor": "<text identifying an existing paragraph>", "paragraphs": ["<new paragraph>", "<another new paragraph>"]}]
```

The three operations:
- Replace (no "op" key): rewrites text inside ONE paragraph. "old" must
  occur exactly once in the draft (set "replace_all": true to change every
  occurrence); "new" replaces it outright, and an empty "new" deletes just
  that text. Quote only the text that changes plus enough surrounding words
  to be unique.
- "delete_paragraph": removes one whole paragraph, heading or body. "text"
  is any quote found in exactly one paragraph. Removing a section means one
  op for its heading and one per body paragraph.
- "insert_after": adds new paragraphs immediately after the paragraph
  identified by "anchor". Each list item is the full plain text of one new
  paragraph.

Any operation may add "occurrence": N when its quoted text appears more
than once in the draft. N counts matches from the top of the document,
1-based. Pleadings repeat boilerplate verbatim (each count's
incorporation paragraph, for example); occurrence is how you target the
one in a specific count. Count the matches yourself in the draft text
below before choosing N.

Rules:
- The block is applied immediately to the attorney's open document as
  tracked changes (redlines). Discussing or suggesting a change is NOT
  direction to make it. Never emit the block unprompted.
- Everything in "old" renders as struck-out text in the redline, even the
  parts "new" repeats verbatim, so a wide "old" buries the real change in
  visual noise. Keep the rewritten span minimal: to add a sentence to a
  paragraph, anchor on the last few words of the preceding sentence (e.g.
  "old": "end of prior sentence.", "new": "end of prior sentence. New
  sentence."), not the whole sentence. Never re-quote a full sentence to
  append after it, and use insert_after (not replace) for new paragraphs.
- All quoted text is PLAIN TEXT exactly as it reads in the draft: strip
  any Markdown markers (**, *, #, etc.), which do not exist in the
  underlying file, and never include newlines inside a string.
- Outside the block, summarize the intent of the edits in a sentence or
  two. Do not restate them line by line.
- The draft below may show numbered-list markers, but they are this
  rendering's own count and can differ from the paragraph numbers the
  attorney sees in the document. When the attorney cites a paragraph
  number, locate the paragraph by its text (ask for a quote if you cannot
  tell which one is meant), and in replies refer to paragraphs by quoting
  their text or using the attorney's numbering. Never cite your own count
  of paragraphs."""


def build_draft_section(link):
    """The draft context appended to the case system prompt when linked.

    Refreshes the stored text from Drive first when it has gone stale with
    no companion connected (the user may have edited and synced the file
    since the last push).
    """
    from apps.drafts import services

    services.refresh_if_stale(link)
    return "\n".join(
        [
            "\n---\n",
            DRAFT_PREAMBLE,
            "",
            EDIT_PROTOCOL,
            "",
            f'THE DRAFT: "{link.name}"',
            "",
            link.doc_text or "(the draft's text could not be read)",
        ]
    )


def _parse_edit_block(raw):
    """Parse one block's JSON into redline op objects, or raise ValueError."""
    data = json.loads(raw)
    if not isinstance(data, list) or not data:
        raise ValueError("draft-edits block is not a non-empty list")
    edits = []
    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError("draft-edits entry is not an object")
        op = entry.get("op", "replace")
        occurrence = entry.get("occurrence")
        if occurrence is not None:
            occurrence = int(occurrence)
        if op == "replace":
            if "old" not in entry:
                raise ValueError("replace entry has no 'old'")
            edits.append(
                RedlineEdit(
                    old=str(entry["old"]),
                    new=str(entry.get("new", "")),
                    replace_all=bool(entry.get("replace_all", False)),
                    occurrence=occurrence,
                )
            )
        elif op == "delete_paragraph":
            edits.append(
                DeleteParagraph(text=str(entry.get("text", "")), occurrence=occurrence)
            )
        elif op == "insert_after":
            paragraphs = entry.get("paragraphs")
            if not isinstance(paragraphs, list):
                raise ValueError("insert_after entry has no paragraphs list")
            edits.append(
                InsertParagraphs(
                    anchor=str(entry.get("anchor", "")),
                    paragraphs=[str(p) for p in paragraphs],
                    occurrence=occurrence,
                )
            )
        else:
            raise ValueError(f"unknown draft-edits op: {op!r}")
    return edits


def apply_edit_blocks(response_text, link):
    """Apply any draft-edits blocks, replacing each with the outcome text.

    A malformed block is left in place as visible text and changes nothing
    (mirrors the agenda/intake block contract). A valid block either goes to
    the connected companion (which applies it to the live document and
    reports back) or is refused with instructions when no companion is
    connected.
    """
    link.refresh_from_db()

    def replace(match):
        try:
            edits = _parse_edit_block(match.group(1).strip())
        except (ValueError, TypeError):
            logger.warning("Unparseable draft-edits block left in place")
            return match.group(0)

        if not link.companion_active:
            return (
                "**The proposed edits were not applied**: the draft is not "
                "connected. Open the document in LibreOffice Writer and use "
                "Kosmos, Connect to drafting session, then ask again."
            )
        return _apply_via_companion(link, edits)

    return DRAFT_EDITS_RE.sub(replace, response_text)


def _apply_via_companion(link, edits):
    """Queue one round for the connected companion and wait for its outcome."""
    round_ = CompanionRound.objects.create(
        link=link, edits=[edit_to_dict(e) for e in edits]
    )
    deadline = time.monotonic() + COMPANION_WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(0.5)
        round_.refresh_from_db()
        if round_.status != "pending":
            break

    if round_.status == "applied":
        count = len(edits)
        plural = "s" if count != 1 else ""
        return (
            f"**Applied {count} edit{plural} as tracked changes in the open "
            "LibreOffice document.** Review them there; save the file when "
            "you are satisfied."
        )
    if round_.status == "failed":
        if round_.edit_index is not None:
            detail = f"edit {round_.edit_index + 1}: {round_.error}"
        else:
            detail = round_.error
        return (
            f"**The proposed edits were not applied** ({detail}). "
            "The document is unchanged."
        )
    round_.status = "expired"
    round_.save(update_fields=["status"])
    logger.warning("Companion round %s expired for link %s", round_.id, link.id)
    return (
        "**The proposed edits were not applied**: the LibreOffice companion "
        "did not respond in time. Check that the document is still open and "
        "connected, then ask again."
    )
