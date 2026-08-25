"""
The agent conversation's working set: materials read in earlier turns,
re-fetched from the database and carried forward verbatim into the next
turn's prompt.

Prior turns' tool transcripts are not replayed into the history (only
the answers carry over), so without this the model would have to re-read
anything it wanted to rely on. Every successful read is already recorded
in Message.agent_run["steps"]; this module re-fetches those materials
fresh each turn — the database is the ground truth, so the carried text
is always exact and current, never a summary. A total cap bounds the
segment; least-recently-read items are evicted first and fall back to
the earlier-reads note (agent_prompt), which tells the model to re-read
them before quoting.
"""

import logging
from dataclasses import dataclass, field

from django.core.cache import cache as django_cache

logger = logging.getLogger(__name__)

READ_KINDS = (
    "document",
    "email",
    "note",
    "library",
    "caselaw",
    "conversation",
    "opinion",
)

WORKING_SET_MAX_CHARS = 200_000
# Matches AgentBudget.default_read_chars: an item carries at most one
# standard read part; the rest stays a tool call away.
WORKING_SET_ITEM_CHARS = 60_000

HEADER = """## Materials in View

The full text of materials read in earlier turns of this conversation,
re-fetched and carried forward. These count as read: rely on them and
cite them normally. Anything you read before that is NOT carried here
must be read again before you quote or characterize it."""


@dataclass
class WorkingSet:
    text: str = ""
    carried: set = field(default_factory=set)
    evicted: int = 0


def reads_from_steps(conversation) -> dict:
    """Successful reads recorded across the conversation's agent turns.

    Returns {(kind, str(id)): {"name", "first", "last"}} where first/last
    are read positions in conversation order — first drives the stable
    rendering order, last drives eviction recency.
    """
    if conversation is None or not getattr(conversation, "pk", None):
        return {}
    reads = {}
    position = 0
    for message in conversation.messages.filter(role="assistant").order_by(
        "created_at", "pk"
    ):
        for step in (message.agent_run or {}).get("steps", []):
            if step.get("type") != "tool" or step.get("error"):
                continue
            if step.get("kind") not in READ_KINDS:
                continue
            key = (step["kind"], str(step.get("id")))
            entry = reads.setdefault(
                key,
                {
                    "name": step.get("name") or str(step.get("id")),
                    "first": position,
                    "last": position,
                },
            )
            entry["last"] = position
            position += 1
    return reads


def _int(ident):
    try:
        return int(ident)
    except (TypeError, ValueError):
        return 0


def _fetch_document(matter, conversation, ident):
    from apps.case.models import Document

    doc = (
        Document.objects.filter(matter=matter, pk=_int(ident))
        .exclude(ai_context="never")
        .first()
    )
    if (
        doc is None
        or doc.ocr_status not in ("completed", "extracted")
        or not doc.ocr_text
    ):
        return ""
    head = f"### Document [doc:{doc.id}]: {doc.name} ({doc.category})"
    if doc.date:
        head += f" - {doc.date}"
    return head + "\n\n" + doc.ocr_text


def _fetch_email_thread(matter, conversation, ident):
    from apps.mail.ai import format_email_thread, thread_subject

    def _thread(field):
        return list(
            matter.emails.filter(**{field: ident})
            .exclude(ai_context="never")
            .dedup()
            .prefetch_related("attachment_files")
        )

    emails = _thread("thread_id") or _thread("gmail_id")
    if not emails:
        return ""
    emails.sort(key=lambda e: e.date or e.created_at)
    head = f"### Email thread [thread:{ident}]: {thread_subject(emails)}"
    return head + "\n\n" + format_email_thread(emails)


def _fetch_note(matter, conversation, ident):
    from apps.notes.models import Note

    note = Note.objects.filter(matter=matter, pk=_int(ident)).first()
    if note is None or not note.content:
        return ""
    head = f"### Note [note:{note.id}]: {note.title} ({note.get_category_display()})"
    return head + "\n\n" + note.content


def _fetch_library_note(matter, conversation, ident):
    from apps.notes.models import get_library_notes

    from .selector import library_folder_path

    note = get_library_notes().filter(pk=_int(ident)).select_related("folder").first()
    if note is None or not note.content:
        return ""
    head = (
        f"### Library note [lib:{note.id}]: {note.title} "
        f"({library_folder_path(note.folder)})"
    )
    return head + "\n\n" + note.content


def _fetch_caselaw(matter, conversation, ident):
    from apps.case.models import CaseLaw

    caselaw = (
        CaseLaw.objects.filter(matter=matter, pk=_int(ident))
        .exclude(ai_context="never")
        .first()
    )
    if caselaw is None:
        return ""
    parts = [
        f"### Saved case [case:{caselaw.id}]: {caselaw.case_name}, {caselaw.citation}"
    ]
    if caselaw.court:
        parts.append(f"Court: {caselaw.court}")
    if caselaw.date_filed:
        parts.append(f"Date: {caselaw.date_filed}")
    if caselaw.notes:
        parts.append(f"Attorney notes:\n{caselaw.notes}")
    if caselaw.summary:
        parts.append(f"Summary:\n{caselaw.summary}")
    # Same key read_caselaw writes; a prompt build never fetches over the
    # network, so an expired cache degrades to a pointer at the tool.
    opinion = django_cache.get(f"agent_opinion_{caselaw.id}")
    if opinion:
        parts.append(f"Opinion:\n{opinion}")
    else:
        parts.append(
            "Opinion text not carried into this turn; use read_caselaw if you need it."
        )
    return "\n\n".join(parts)


def _fetch_conversation(matter, conversation, ident):
    from .models import Conversation

    conv = (
        Conversation.objects.filter(matter=matter, pk=_int(ident))
        .exclude(pk=getattr(conversation, "pk", None) or 0)
        .exclude(ai_context="never")
        .first()
    )
    if conv is None:
        return ""
    lines = [f"### Earlier conversation [conv:{conv.id}]: {conv.title or 'Untitled'}"]
    for msg in conv.messages.select_related("user").order_by("created_at"):
        if msg.role == "user":
            who = msg.user.get_full_name() if msg.user else "User"
        else:
            who = "Assistant"
        lines.append(f"**{who}:** {msg.content}")
    return "\n\n".join(lines)


def _fetch_opinion(matter, conversation, ident):
    # Cache only, never the network (same rule as caselaw): read_opinion
    # fills agent_opinion_cluster_{id}; an expired entry just falls back
    # to the earlier-reads note.
    data = django_cache.get(f"agent_opinion_cluster_{_int(ident)}")
    if not data or not data.get("text"):
        return ""
    head = f"### Opinion [cluster:{data['cluster_id']}]: {data['case_name']}"
    if data.get("citation"):
        head += f", {data['citation']}"
    return head + "\n\n" + data["text"]


_FETCHERS = {
    "document": _fetch_document,
    "email": _fetch_email_thread,
    "note": _fetch_note,
    "library": _fetch_library_note,
    "caselaw": _fetch_caselaw,
    "conversation": _fetch_conversation,
    "opinion": _fetch_opinion,
}


def _capped(block: str) -> str:
    if len(block) <= WORKING_SET_ITEM_CHARS:
        return block
    return block[:WORKING_SET_ITEM_CHARS] + (
        f"\n\n[First {WORKING_SET_ITEM_CHARS:,} of {len(block):,} characters "
        "carried; use the matching read tool for the rest.]"
    )


def build_working_set(
    conversation, matter, max_chars: int = WORKING_SET_MAX_CHARS
) -> WorkingSet:
    """The Materials in View segment for one agent turn.

    Re-fetches every material the conversation has read, newest first,
    keeping each while the total fits ``max_chars``; what does not fit is
    evicted (counted, and left to the earlier-reads note). Kept items
    render in first-read order so the segment grows append-only across
    turns, which keeps the prompt-cache prefix stable.
    """
    reads = reads_from_steps(conversation)
    if not reads or max_chars <= 0:
        return WorkingSet(evicted=len(reads) if max_chars <= 0 else 0)

    # Items that no longer fetch (deleted, or newly excluded from AI use)
    # are neither carried nor counted as evicted; the earlier-reads note
    # still names them, same as before this segment existed.
    fetched = []
    for key, entry in reads.items():
        try:
            block = _FETCHERS[key[0]](matter, conversation, key[1])
        except Exception:
            logger.exception("Working set fetch failed for %s", key)
            block = ""
        if block:
            fetched.append((key, entry, _capped(block)))

    kept = []
    total = len(HEADER)
    evicted = 0
    for key, entry, block in sorted(fetched, key=lambda t: -t[1]["last"]):
        if total + len(block) + 2 > max_chars:
            evicted += 1
            continue
        total += len(block) + 2
        kept.append((key, entry, block))

    if not kept:
        return WorkingSet(evicted=evicted)
    kept.sort(key=lambda t: t[1]["first"])
    text = "\n\n".join([HEADER] + [block for _, _, block in kept])
    return WorkingSet(text=text, carried={key for key, _, _ in kept}, evicted=evicted)
