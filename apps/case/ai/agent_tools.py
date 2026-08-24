"""
Tools for the agentic chat mode.

The agent turn (agent.py) gives the model a small orientation prompt and
these read-only tools instead of a preloaded matter context; the model
opens what it needs. Three pieces live here:

- ``build_agent_tools`` returns provider-neutral tool specs
  ({"name", "description", "input_schema"}) that both provider loops
  translate (Anthropic takes them as is; Gemini gets FunctionDeclarations).
- ``make_agent_executor`` returns ``execute_batch(calls) -> outcomes``:
  the handlers, a per-turn budget (calls and characters read), a dedupe
  cache so an exact repeat of a call is served free and flagged, and the
  step events the live status box renders.
- ``run_tool_batch`` runs one model turn's calls concurrently while
  preserving their order, which is what both loops need to answer the
  turn with results in block order.

Every tool result is a JSON object; failures come back as {"error": ...}
so the model can react instead of the run dying. Writes stay on the
fenced-block path (tasks.finalize_response), shared with the classic chat.
"""

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from django.core.cache import cache as django_cache
from django.db import connections
from django.db.models import Q

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentBudget:
    """Per-turn limits the executor enforces and the prompt announces."""

    max_tool_calls: int = 25
    max_chars: int = 600_000
    default_read_chars: int = 60_000
    max_read_chars: int = 150_000
    max_turns: int = 30
    parallel_workers: int = 4


DEFAULT_BUDGET = AgentBudget()

SEARCH_KINDS = ("document", "note", "library", "email", "highlight", "fact")
SEARCH_DEFAULT_LIMIT = 15
SEARCH_MAX_LIMIT = 40
SNIPPET_CHARS = 300
SECTION_CAP = 150_000
OPINION_CACHE_SECONDS = 3600

# A search whose hits were mostly returned by an earlier search this turn
# earns a note; the research loop showed rephrase-looping burns budget.
OVERLAP_SHARE = 0.7

BUDGET_EXHAUSTED = (
    "Tool budget exhausted ({calls} calls, {chars:,} characters read this "
    "turn). Answer now from what you have read."
)
READ_BUDGET_EXHAUSTED = (
    "Reading budget exhausted ({chars:,} characters this turn). Answer now "
    "from what you have read."
)
REPEAT_NOTE = (
    "You already made this exact call this turn; the same result is "
    "returned and not charged. Change the input instead of repeating it."
)


def _read_params(extra: dict | None = None) -> dict:
    """The offset/max_chars pair every text read accepts."""
    props = {
        "offset": {
            "type": "integer",
            "description": (
                "Character offset to start from, for reading a long text in "
                "parts. Use next_offset from the previous part. Defaults to 0."
            ),
        },
        "max_chars": {
            "type": "integer",
            "description": (
                "Characters to return in this part. Defaults to the standard "
                "part size; larger values are capped."
            ),
        },
    }
    props.update(extra or {})
    return props


def build_agent_tools(budget: AgentBudget = DEFAULT_BUDGET) -> list[dict]:
    """Provider-neutral tool specs for one agent turn."""
    return [
        {
            "name": "search_materials",
            "description": (
                "Full-text search across this matter's materials: documents "
                "(OCR text), matter notes, firm library notes, synced emails, "
                "highlights and timeline facts. Returns ranked hits with a "
                "short snippet and the handle to read the full item. Use it "
                "to find which materials to read when the index alone does "
                "not tell you; do not repeat a search with the same words."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search terms (a few specific words).",
                    },
                    "kinds": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(SEARCH_KINDS)},
                        "description": (
                            "Restrict to these kinds. Defaults to all kinds."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            f"Maximum hits, default {SEARCH_DEFAULT_LIMIT}, "
                            f"at most {SEARCH_MAX_LIMIT}."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "read_document",
            "description": (
                "The extracted text of a document in the index ([doc:ID]). "
                f"Long documents come in parts of {budget.default_read_chars:,} "
                "characters; the result reports total_chars and next_offset."
            ),
            "input_schema": {
                "type": "object",
                "properties": _read_params(
                    {"doc_id": {"type": "integer", "description": "Document id."}}
                ),
                "required": ["doc_id"],
            },
        },
        {
            "name": "read_email_thread",
            "description": (
                "A synced email thread in full ([thread:ID] in the index), "
                "oldest message first, with attachment names."
            ),
            "input_schema": {
                "type": "object",
                "properties": _read_params(
                    {
                        "thread_id": {
                            "type": "string",
                            "description": "Thread id from the index or a search hit.",
                        }
                    }
                ),
                "required": ["thread_id"],
            },
        },
        {
            "name": "read_note",
            "description": (
                "A matter note ([note:ID]) or a firm library note ([lib:ID]) "
                "in full, as markdown."
            ),
            "input_schema": {
                "type": "object",
                "properties": _read_params(
                    {"note_id": {"type": "integer", "description": "Note id."}}
                ),
                "required": ["note_id"],
            },
        },
        {
            "name": "read_caselaw",
            "description": (
                "A case saved to this matter ([case:ID]): the attorney's notes, "
                "the summary, and the opinion text fetched from CourtListener."
            ),
            "input_schema": {
                "type": "object",
                "properties": _read_params(
                    {
                        "caselaw_id": {
                            "type": "integer",
                            "description": "Saved case id.",
                        }
                    }
                ),
                "required": ["caselaw_id"],
            },
        },
        {
            "name": "read_conversation",
            "description": (
                "The transcript of an earlier AI conversation on this matter "
                "([conv:ID]); useful when the index summary suggests it "
                "already analyzed the question."
            ),
            "input_schema": {
                "type": "object",
                "properties": _read_params(
                    {
                        "conversation_id": {
                            "type": "integer",
                            "description": "Conversation id.",
                        }
                    }
                ),
                "required": ["conversation_id"],
            },
        },
        {
            "name": "read_invoice",
            "description": (
                "One invoice on this matter ([inv:ID]) with its line items "
                "and balance. Only for billing questions."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "invoice_id": {"type": "integer", "description": "Invoice id."}
                },
                "required": ["invoice_id"],
            },
        },
        {
            "name": "read_matter_section",
            "description": (
                "A structured section of the matter record as text: "
                "overview, contacts, rates, activity (time and expenses), "
                "events, tasks, proceedings, settlement, documents (the "
                "manifest), highlights, timeline, witnesses, emails (the "
                "thread manifest). The overview, contacts, witnesses and "
                "proceedings are already in your orientation; read the others "
                "when the question needs them."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "enum": [
                            "overview",
                            "contacts",
                            "rates",
                            "activity",
                            "events",
                            "tasks",
                            "proceedings",
                            "settlement",
                            "documents",
                            "highlights",
                            "timeline",
                            "witnesses",
                            "emails",
                        ],
                        "description": "Section name.",
                    }
                },
                "required": ["section"],
            },
        },
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _k(n: int) -> str:
    """41k / 812 style size for step labels."""
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.0f}k"
    return str(n)


def _snippet(text: str, query: str, width: int = SNIPPET_CHARS) -> str:
    """A window of ``text`` centred on the first query term it contains."""
    text = (text or "").replace("\n", " ").strip()
    if not text:
        return ""
    lower = text.lower()
    pos = -1
    for term in query.lower().split():
        pos = lower.find(term)
        if pos >= 0:
            break
    if pos < 0:
        return text[:width] + ("..." if len(text) > width else "")
    start = max(0, pos - width // 2)
    end = min(len(text), start + width)
    piece = text[start:end]
    if start > 0:
        piece = "..." + piece
    if end < len(text):
        piece += "..."
    return piece


PENDING_LABELS = {
    "search_materials": 'Searching "{query}"...',
    "read_document": "Reading document {doc_id}...",
    "read_email_thread": "Reading email thread {thread_id}...",
    "read_note": "Reading note {note_id}...",
    "read_caselaw": "Reading saved case {caselaw_id}...",
    "read_conversation": "Reading conversation {conversation_id}...",
    "read_invoice": "Reading invoice {invoice_id}...",
    "read_matter_section": "Reading the {section} section...",
}


def _pending_label(name: str, tool_input: dict) -> str:
    """The status line while a call runs, before its result names it."""
    template = PENDING_LABELS.get(name)
    if not template:
        return f"Running {name}..."
    try:
        return template.format(
            **{k: str(v)[:60] for k, v in (tool_input or {}).items()}
        )
    except (KeyError, IndexError):
        return f"Running {name}..."


def _canonical(name: str, tool_input: dict) -> str:
    return name + ":" + json.dumps(tool_input or {}, sort_keys=True, default=str)


def run_tool_batch(calls: list[dict], execute_one, max_workers: int) -> list[dict]:
    """Run one turn's calls, concurrently when there are several.

    Results come back in the calls' order. A handler that raises yields an
    error outcome for that call; nothing escapes. The inline path (one
    call, or a worker cap of one) is also what tests that stub
    threading.Thread rely on.
    """
    if len(calls) <= 1 or max_workers <= 1:
        return [execute_one(call) for call in calls]

    def worker(call):
        try:
            return execute_one(call)
        finally:
            # ORM use opens a connection per pool thread; release it.
            connections.close_all()

    with ThreadPoolExecutor(max_workers=min(max_workers, len(calls))) as pool:
        return list(pool.map(worker, calls))


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


def make_agent_executor(
    matter,
    conversation,
    budget: AgentBudget = DEFAULT_BUDGET,
    on_event=None,
    is_cancelled=None,
):
    """Build ``execute_batch(calls) -> outcomes`` for one agent turn.

    ``calls`` are ``{"id", "name", "input"}``; outcomes are ``{"id",
    "name", "content": json string, "is_error"}`` in the same order.
    ``on_event(step)`` fires when a call starts (``pending`` True) and
    again on the same dict when it finishes, so the live log shows one
    row per tool that fills in. ``execute_batch.set_turn(n)`` tags the
    steps with the model turn; ``execute_batch.usage()`` reports the
    counters for the status payload.
    """
    from apps.case.models import CaseLaw, Document, Fact, Highlight
    from apps.invoicing.invoices.models import Invoice
    from apps.mail.ai import format_email_thread, group_by_thread, thread_subject
    from apps.notes.models import Note, get_library_notes

    from .models import Conversation
    from .selector import library_folder_path

    lock = threading.Lock()
    state = {"calls": 0, "chars": 0, "n": 0, "turn": 0}
    results_cache: dict[str, dict] = {}
    seen_hits: set[tuple[str, str]] = set()

    def _budget():
        return {
            "calls_left": max(0, budget.max_tool_calls - state["calls"]),
            "chars_left": max(0, budget.max_chars - state["chars"]),
        }

    def _charge_chars(n: int):
        with lock:
            state["chars"] += n

    def _chars_left():
        return max(0, budget.max_chars - state["chars"])

    def _slice(text: str, tool_input: dict) -> tuple[dict, int]:
        """Apply offset/max_chars to ``text``; returns (fields, chars)."""
        total = len(text)
        try:
            offset = max(0, int(tool_input.get("offset") or 0))
        except (TypeError, ValueError):
            offset = 0
        try:
            requested = int(tool_input.get("max_chars") or budget.default_read_chars)
        except (TypeError, ValueError):
            requested = budget.default_read_chars
        size = max(1, min(requested, budget.max_read_chars, _chars_left()))
        chunk = text[offset : offset + size]
        end = offset + len(chunk)
        fields = {
            "text": chunk,
            "total_chars": total,
            "offset": offset,
            "next_offset": end if end < total else None,
            "truncated": end < total,
        }
        return fields, len(chunk)

    def _part_detail(fields: dict) -> str:
        """The outcome half of a read: size, or the slice read."""
        total = fields["total_chars"]
        if fields["offset"] == 0 and not fields["truncated"]:
            return f"{_k(total)} chars"
        start = fields["offset"]
        end = start + len(fields["text"])
        return f"chars {start:,} to {end:,} of {_k(total)}"

    def _part_label(verb: str, name: str, fields: dict) -> str:
        return f"{verb} *{name}* ({_part_detail(fields)})"

    # -- handlers: return (payload, step_fields) ---------------------------

    def _search(tool_input):
        from watson import search as watson

        query = str(tool_input.get("query") or "").strip()
        if not query:
            return {"error": "query is required."}, {}
        kinds = tool_input.get("kinds") or list(SEARCH_KINDS)
        kinds = [k for k in kinds if k in SEARCH_KINDS] or list(SEARCH_KINDS)
        try:
            limit = int(tool_input.get("limit") or SEARCH_DEFAULT_LIMIT)
        except (TypeError, ValueError):
            limit = SEARCH_DEFAULT_LIMIT
        limit = max(1, min(limit, SEARCH_MAX_LIMIT))

        querysets = []
        if "document" in kinds:
            querysets.append(
                Document.objects.filter(matter=matter).exclude(ai_context="never")
            )
        if "highlight" in kinds:
            # Scoped through a subquery so the outer queryset carries no
            # join: watson's SQL selects a bare "id" from it.
            scoped = Highlight.objects.filter(
                Q(document__matter=matter) | Q(caselaw__matter=matter)
            ).values("pk")
            querysets.append(Highlight.objects.filter(pk__in=scoped))
        if "fact" in kinds:
            querysets.append(Fact.objects.filter(matter=matter))
        if "note" in kinds:
            querysets.append(Note.objects.filter(matter=matter))
        if "library" in kinds:
            querysets.append(get_library_notes())

        hits = []
        if querysets:
            for result in watson.search(query, models=tuple(querysets))[:limit]:
                obj = result.object
                if obj is None:
                    continue
                if isinstance(obj, Document):
                    hits.append(
                        {
                            "kind": "document",
                            "id": obj.id,
                            "handle": f"doc:{obj.id}",
                            "name": obj.name,
                            "category": obj.category,
                            "date": str(obj.date) if obj.date else None,
                            "snippet": _snippet(obj.ocr_text or "", query),
                        }
                    )
                elif isinstance(obj, Highlight):
                    source = obj.document or obj.caselaw
                    hit = {
                        "kind": "highlight",
                        "id": obj.id,
                        "handle": f"hl:{obj.id}",
                        "name": obj.citation,
                        "category": obj.color,
                        "date": None,
                        "snippet": _snippet(obj.text, query),
                    }
                    if obj.document_id:
                        hit["document_id"] = obj.document_id
                        hit["date"] = str(source.date) if source.date else None
                    elif obj.caselaw_id:
                        hit["caselaw_id"] = obj.caselaw_id
                    hits.append(hit)
                elif isinstance(obj, Fact):
                    hits.append(
                        {
                            "kind": "fact",
                            "id": obj.id,
                            "handle": f"fact:{obj.id}",
                            "name": obj.description or "",
                            "category": "timeline",
                            "date": str(obj.date) if obj.date else None,
                            "snippet": obj.description or "",
                        }
                    )
                elif isinstance(obj, Note):
                    library = obj.matter_id is None
                    hits.append(
                        {
                            "kind": "library" if library else "note",
                            "id": obj.id,
                            "handle": f"{'lib' if library else 'note'}:{obj.id}",
                            "name": obj.title,
                            "category": (
                                f"Library: {library_folder_path(obj.folder)}"
                                if library
                                else obj.get_category_display()
                            ),
                            "date": (
                                str(obj.updated_at.date()) if obj.updated_at else None
                            ),
                            "snippet": _snippet(obj.content or "", query),
                        }
                    )

        if "email" in kinds and len(hits) < limit:
            emails = (
                matter.emails.filter(
                    Q(subject__icontains=query) | Q(body_text__icontains=query)
                )
                .exclude(ai_context="never")
                .dedup()
            )
            for thread_emails in group_by_thread(emails):
                if len(hits) >= limit:
                    break
                first, last = thread_emails[0], thread_emails[-1]
                key = first.thread_id or first.gmail_id
                match = next(
                    (e for e in thread_emails if query.lower() in e.body_text.lower()),
                    last,
                )
                hits.append(
                    {
                        "kind": "email",
                        "id": key,
                        "handle": f"thread:{key}",
                        "name": thread_subject(thread_emails),
                        "category": f"Email thread, {len(thread_emails)} messages",
                        "date": f"{last.date:%Y-%m-%d}" if last.date else None,
                        "snippet": _snippet(match.body_text or match.snippet, query),
                    }
                )

        seen_count = 0
        with lock:
            for hit in hits:
                key = (hit["kind"], str(hit["id"]))
                hit["seen"] = key in seen_hits
                seen_count += hit["seen"]
                seen_hits.add(key)
        payload = {"query": query, "hits": hits, "total": len(hits)}
        if len(hits) >= 3 and seen_count / len(hits) >= OVERLAP_SHARE:
            payload["note"] = (
                "Most of these hits came back from an earlier search this "
                "turn. Use different terms, or read what you already found."
            )
        seen = f", {seen_count} seen before" if seen_count else ""
        label = f'Searched "{query}" ({len(hits)} hits{seen})'
        return payload, {
            "label": label,
            "title": f'Searched "{query}"',
            "detail": f"{len(hits)} hits{seen}",
            "query": query,
            "kinds": kinds,
            "hits": len(hits),
            "seen": seen_count,
            "chars": 0,
        }

    def _read_document(tool_input):
        doc = Document.objects.filter(
            matter=matter, pk=tool_input.get("doc_id") or 0
        ).first()
        if doc is None:
            return {"error": "No such document on this matter."}, {}
        if doc.ai_context == "never":
            return {"error": f"Document {doc.id} is excluded from AI use."}, {}
        if doc.ocr_status not in ("completed", "extracted") or not doc.ocr_text:
            return {
                "error": (
                    f"Document {doc.id} has no extracted text "
                    f"(OCR status {doc.ocr_status})."
                )
            }, {}
        fields, chars = _slice(doc.ocr_text, tool_input)
        payload = {
            "doc_id": doc.id,
            "name": doc.name,
            "category": doc.category,
            "date": str(doc.date) if doc.date else None,
            **fields,
        }
        return payload, {
            "label": _part_label("Read", doc.name, fields),
            "title": f"Read *{doc.name}*",
            "detail": _part_detail(fields),
            "kind": "document",
            "id": doc.id,
            "name": doc.name,
            "chars": chars,
            "total_chars": fields["total_chars"],
        }

    def _read_email_thread(tool_input):
        thread_id = str(tool_input.get("thread_id") or "").strip()
        if not thread_id:
            return {"error": "thread_id is required."}, {}
        emails = list(
            matter.emails.filter(thread_id=thread_id)
            .exclude(ai_context="never")
            .dedup()
            .prefetch_related("attachment_files")
        )
        if not emails:
            emails = list(
                matter.emails.filter(gmail_id=thread_id)
                .exclude(ai_context="never")
                .dedup()
                .prefetch_related("attachment_files")
            )
        if not emails:
            return {"error": "No such email thread on this matter."}, {}
        emails.sort(key=lambda e: e.date or e.created_at)
        subject = thread_subject(emails)
        fields, chars = _slice(format_email_thread(emails), tool_input)
        payload = {
            "thread_id": thread_id,
            "subject": subject,
            "messages": len(emails),
            **fields,
        }
        return payload, {
            "label": _part_label("Read thread", subject, fields),
            "title": f"Read thread *{subject}*",
            "detail": _part_detail(fields),
            "kind": "email",
            "id": thread_id,
            "name": subject,
            "chars": chars,
            "total_chars": fields["total_chars"],
        }

    def _read_note(tool_input):
        note = (
            Note.objects.filter(pk=tool_input.get("note_id") or 0)
            .select_related("folder")
            .first()
        )
        library = False
        if note is not None and note.matter_id == matter.id:
            pass
        elif (
            note is not None
            and note.matter_id is None
            and get_library_notes().filter(pk=note.pk).exists()
        ):
            library = True
        else:
            note = None
        if note is None:
            return {"error": "No such note on this matter or in the library."}, {}
        fields, chars = _slice(note.content or "", tool_input)
        payload = {
            "note_id": note.id,
            "title": note.title,
            "library": library,
            "folder": library_folder_path(note.folder) if library else "",
            "category": note.get_category_display(),
            "topic": note.topic or "",
            **fields,
        }
        return payload, {
            "label": _part_label(
                "Read library note" if library else "Read note", note.title, fields
            ),
            "title": (
                f"Read library note *{note.title}*"
                if library
                else f"Read note *{note.title}*"
            ),
            "detail": _part_detail(fields),
            "kind": "library" if library else "note",
            "id": note.id,
            "name": note.title,
            "chars": chars,
            "total_chars": fields["total_chars"],
        }

    def _read_caselaw(tool_input):
        from .context import _fetch_caselaw_opinion_text

        caselaw = CaseLaw.objects.filter(
            matter=matter, pk=tool_input.get("caselaw_id") or 0
        ).first()
        if caselaw is None:
            return {"error": "No such saved case on this matter."}, {}
        if caselaw.ai_context == "never":
            return {"error": f"Case {caselaw.id} is excluded from AI use."}, {}
        cache_key = f"agent_opinion_{caselaw.id}"
        opinion = django_cache.get(cache_key)
        if opinion is None:
            opinion = _fetch_caselaw_opinion_text(caselaw) or ""
            django_cache.set(cache_key, opinion, OPINION_CACHE_SECONDS)
        parts = [f"{caselaw.case_name}, {caselaw.citation}"]
        if caselaw.court:
            parts.append(f"Court: {caselaw.court}")
        if caselaw.date_filed:
            parts.append(f"Date: {caselaw.date_filed}")
        if caselaw.notes:
            parts.append(f"Attorney notes:\n{caselaw.notes}")
        if caselaw.summary:
            parts.append(f"Summary:\n{caselaw.summary}")
        if opinion:
            parts.append(f"Opinion:\n{opinion}")
        else:
            parts.append("Opinion text unavailable.")
        fields, chars = _slice("\n\n".join(parts), tool_input)
        payload = {
            "caselaw_id": caselaw.id,
            "case_name": caselaw.case_name,
            "citation": caselaw.citation,
            "cluster_id": caselaw.cluster_id,
            **fields,
        }
        return payload, {
            "label": _part_label("Read", caselaw.case_name, fields),
            "title": f"Read *{caselaw.case_name}*",
            "detail": _part_detail(fields),
            "kind": "caselaw",
            "id": caselaw.id,
            "name": caselaw.case_name,
            "chars": chars,
            "total_chars": fields["total_chars"],
        }

    def _read_conversation(tool_input):
        conv = (
            Conversation.objects.filter(
                matter=matter, pk=tool_input.get("conversation_id") or 0
            )
            .exclude(pk=getattr(conversation, "pk", None) or 0)
            .exclude(ai_context="never")
            .first()
        )
        if conv is None:
            return {"error": "No such earlier conversation on this matter."}, {}
        lines = [f"Conversation: {conv.title or 'Untitled'}"]
        for msg in conv.messages.select_related("user").order_by("created_at"):
            if msg.role == "user":
                who = msg.user.get_full_name() if msg.user else "User"
            else:
                who = "Assistant"
            lines.append(f"**{who}:** {msg.content}")
        fields, chars = _slice("\n\n".join(lines), tool_input)
        name = conv.title or "Untitled"
        payload = {"conversation_id": conv.id, "title": name, **fields}
        return payload, {
            "label": _part_label("Read conversation", name, fields),
            "title": f"Read conversation *{name}*",
            "detail": _part_detail(fields),
            "kind": "conversation",
            "id": conv.id,
            "name": name,
            "chars": chars,
            "total_chars": fields["total_chars"],
        }

    def _read_invoice(tool_input):
        from .context import format_invoice

        invoice = Invoice.objects.filter(
            matter=matter, pk=tool_input.get("invoice_id") or 0
        ).first()
        if invoice is None:
            return {"error": "No such invoice on this matter."}, {}
        text = format_invoice(invoice)
        name = f"Invoice #{invoice.id}"
        return {"invoice_id": invoice.id, "text": text}, {
            "label": f"Read *{name}*",
            "title": f"Read *{name}*",
            "detail": f"{_k(len(text))} chars",
            "kind": "invoice",
            "id": invoice.id,
            "name": name,
            "chars": len(text),
            "total_chars": len(text),
        }

    def _read_section(tool_input):
        from apps.case.api import SECTIONS

        section = str(tool_input.get("section") or "")
        if section not in SECTIONS:
            return {
                "error": f"Unknown section. Valid sections: {', '.join(SECTIONS)}."
            }, {}
        text = SECTIONS[section](matter)[:SECTION_CAP]
        return {"section": section, "text": text}, {
            "label": f"Read the {section} section ({_k(len(text))} chars)",
            "title": f"Read the {section} section",
            "detail": f"{_k(len(text))} chars",
            "kind": "section",
            "id": section,
            "name": section,
            "chars": len(text),
            "total_chars": len(text),
        }

    handlers = {
        "search_materials": _search,
        "read_document": _read_document,
        "read_email_thread": _read_email_thread,
        "read_note": _read_note,
        "read_caselaw": _read_caselaw,
        "read_conversation": _read_conversation,
        "read_invoice": _read_invoice,
        "read_matter_section": _read_section,
    }

    # -- dispatch -----------------------------------------------------------

    def _outcome(call, payload, is_error):
        payload = dict(payload)
        payload["budget"] = _budget()
        return {
            "id": call.get("id"),
            "name": call.get("name"),
            "content": json.dumps(payload, default=str),
            "is_error": bool(is_error),
        }

    def _emit(step):
        if on_event:
            try:
                on_event(step)
            except Exception:
                logger.exception("Agent step event failed")

    def execute_one(call):
        name = call.get("name") or ""
        tool_input = call.get("input") or {}
        handler = handlers.get(name)
        with lock:
            state["n"] += 1
            n = state["n"]
        step = {
            "type": "tool",
            "tool": name,
            "n": n,
            "turn": state["turn"],
            "ts": time.time(),
            "seconds": 0.0,
            "label": _pending_label(name, tool_input),
            "title": _pending_label(name, tool_input),
            "detail": "",
            "pending": True,
            "error": None,
            "repeat": False,
        }
        started = time.time()

        def finish(payload, step_fields, is_error=False):
            step.update(step_fields)
            step["pending"] = False
            step["seconds"] = round(time.time() - started, 2)
            if is_error:
                step["error"] = payload.get("error", "error")
                step["label"] = f"{name}: {step['error']}"
            _emit(step)
            return _outcome(call, payload, is_error)

        if handler is None:
            _emit(step)
            return finish({"error": f"Unknown tool {name!r}."}, {}, True)
        if is_cancelled and is_cancelled():
            _emit(step)
            return finish({"error": "Request cancelled."}, {}, True)

        key = _canonical(name, tool_input)
        with lock:
            cached = results_cache.get(key)
            if cached is None:
                if state["calls"] >= budget.max_tool_calls:
                    exhausted = True
                else:
                    exhausted = False
                    state["calls"] += 1
        if cached is not None:
            step["repeat"] = True
            _emit(step)
            payload = dict(cached["payload"])
            payload["note"] = REPEAT_NOTE
            fields = dict(cached["step"])
            fields["label"] = fields.get("label", name) + " (repeat, not charged)"
            detail = fields.get("detail") or ""
            fields["detail"] = (
                f"{detail}, repeat, not charged" if detail else "repeat, not charged"
            )
            fields["chars"] = 0
            return finish(payload, fields, cached["is_error"])
        if exhausted:
            _emit(step)
            return finish(
                {
                    "error": BUDGET_EXHAUSTED.format(
                        calls=budget.max_tool_calls, chars=state["chars"]
                    )
                },
                {},
                True,
            )
        if name != "search_materials" and _chars_left() <= 0:
            _emit(step)
            return finish(
                {"error": READ_BUDGET_EXHAUSTED.format(chars=state["chars"])},
                {},
                True,
            )

        _emit(step)
        try:
            payload, step_fields = handler(tool_input)
        except Exception:
            logger.exception("Agent tool %s failed", name)
            payload, step_fields = (
                {"error": f"Tool {name} failed; try differently."},
                {},
            )
        is_error = "error" in payload
        if not is_error:
            _charge_chars(int(step_fields.get("chars") or 0))
            with lock:
                results_cache[key] = {
                    "payload": payload,
                    "step": step_fields,
                    "is_error": False,
                }
        return finish(payload, step_fields, is_error)

    def execute_batch(calls):
        return run_tool_batch(calls, execute_one, budget.parallel_workers)

    def set_turn(n):
        state["turn"] = n

    def usage():
        return {
            "tool_calls": state["calls"],
            "tool_calls_max": budget.max_tool_calls,
            "chars_read": state["chars"],
            "chars_read_max": budget.max_chars,
        }

    execute_batch.set_turn = set_turn
    execute_batch.usage = usage
    execute_batch.execute_one = execute_one
    return execute_batch
