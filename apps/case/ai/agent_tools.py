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

from .semantic import semantic_entries

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentBudget:
    """Per-turn limits the executor enforces and the prompt announces."""

    max_tool_calls: int = 40
    max_chars: int = 600_000
    default_read_chars: int = 60_000
    max_read_chars: int = 150_000
    max_turns: int = 30
    parallel_workers: int = 4


DEFAULT_BUDGET = AgentBudget()

SEARCH_KINDS = ("document", "note", "library", "email", "highlight", "fact")
SEARCH_DEFAULT_LIMIT = 15
SEARCH_MAX_LIMIT = 40
SEARCH_MAX_QUERIES = 5
# word_similarity floor for the typo-tolerant fallback.
SEARCH_FUZZY_FLOOR = 0.4
SNIPPET_CHARS = 300
SECTION_CAP = 150_000
OPINION_CACHE_SECONDS = 3600

# CourtListener research tools. Opinion text is immutable, so fetched
# clusters cache for a day (LocMem, so a worker reload clears it anyway);
# the working set carries opinions from this cache only.
CASELAW_SEARCH_DEFAULT_LIMIT = 10
CASELAW_SEARCH_MAX_LIMIT = 20
OPINION_TEXT_CACHE_SECONDS = 86_400
OPINION_TEXT_CAP = 250_000
GREP_DEFAULT_WIDTH = 600
GREP_MAX_WIDTH = 1500
GREP_MAX_MATCHES = 8
GREP_MAX_OPINIONS = 10

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
                "Hybrid search across this matter's materials: documents "
                "(OCR text), matter notes, firm library notes, synced emails, "
                "highlights and timeline facts. Matches by meaning as well as "
                "by words (semantic neighbors are merged with the keyword "
                "hits). Keyword side: words are stemmed and ANDed; "
                'use "quoted phrases" for exact wording, OR between '
                "alternatives, and -word to exclude. Prefer `queries` with 2 "
                "to 4 differently phrased variants (synonyms, terms of art, "
                "statute numbers): one call runs them all, merges the ranked "
                "hits, and flags which variants matched. When nothing "
                "matches, near-miss titles come back as fuzzy hits. Each hit "
                "carries a snippet and the handle to read the full item; "
                "document and library hits also carry an AI summary when one "
                "exists, useful for triage before reading."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A single search (prefer queries).",
                    },
                    "queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Two to four differently phrased searches, run "
                            "together and merged."
                        ),
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
        {
            "name": "search_caselaw",
            "description": (
                "Search published court opinions on CourtListener. This is "
                "relevance-ranked full-text search (Solr), NOT a Boolean "
                "terms-and-connectors engine: AND is the default between "
                'terms, OR for true alternatives, "quoted phrases" for exact '
                "wording, stem* wildcards for inflections (moot* covers moot, "
                'mooted, mootness), "phrase"~N for proximity. Quote statute '
                'numbers bare, without subsections ("9-11-21", never '
                '"9-11-21(a)"); statute numbers are the highest-precision '
                "anchors, and pairing two interacting statutes in one query "
                "finds the doctrine that lives in their interaction. Always "
                "filter by state; each follow-up query must change WHAT is "
                "asked, never reshuffle the same terms. Hits with a "
                "citation are published and citable (published: true); "
                "prefer them. Hits carry cluster_id for read_opinion and "
                "search_in_opinions."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A single search (prefer queries).",
                    },
                    "queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Two to three differently phrased searches, run "
                            "together and merged."
                        ),
                    },
                    "state": {
                        "type": "string",
                        "description": (
                            "Two-letter state id (e.g. ga) to search that "
                            "state's supreme and appellate courts. Defaults "
                            "to the matter's jurisdiction; pass it "
                            "explicitly when you know it."
                        ),
                    },
                    "include_federal": {
                        "type": "boolean",
                        "description": (
                            "Also search the state's federal district "
                            "courts, its circuit, and SCOTUS."
                        ),
                    },
                    "filed_after": {
                        "type": "string",
                        "description": (
                            "YYYY-MM-DD; only opinions filed after this "
                            "date. Use for currency checks."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            f"Maximum hits per query, default "
                            f"{CASELAW_SEARCH_DEFAULT_LIMIT}, at most "
                            f"{CASELAW_SEARCH_MAX_LIMIT}."
                        ),
                    },
                },
            },
        },
        {
            "name": "lookup_citation",
            "description": (
                'Resolve one reporter citation (e.g. "267 Ga. App. 431") '
                "to its case: name, court, date, cluster_id. Citation "
                "lookup is exact where name search is unreliable — route "
                "verification of any case you plan to rely on through its "
                "citation, and use this to chase the authorities an anchor "
                "opinion cites."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "citation": {
                        "type": "string",
                        "description": "One reporter citation.",
                    }
                },
                "required": ["citation"],
            },
        },
        {
            "name": "read_opinion",
            "description": (
                "The full text of a CourtListener opinion cluster "
                "(majority first, then concurrences and dissents), by "
                "cluster_id from search_caselaw or lookup_citation. "
                f"Long opinions come in parts of "
                f"{budget.default_read_chars:,} characters. Prefer "
                "search_in_opinions to locate the passage first, then read "
                "the slice around it; full reads are the exception."
            ),
            "input_schema": {
                "type": "object",
                "properties": _read_params(
                    {
                        "cluster_id": {
                            "type": "integer",
                            "description": "CourtListener cluster id.",
                        }
                    }
                ),
                "required": ["cluster_id"],
            },
        },
        {
            "name": "search_in_opinions",
            "description": (
                "Find every occurrence of a literal phrase inside up to "
                f"{GREP_MAX_OPINIONS} opinions at once (case-insensitive "
                "exact substring, not term search), returning excerpt "
                "windows with character offsets you can follow with a "
                "targeted read_opinion slice. The cheap way to mine an "
                "anchor opinion: grep the statute number or doctrine "
                "phrase to find the rule statement and the cases it "
                "cites, instead of reading the whole opinion."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "cluster_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": (
                            f"Up to {GREP_MAX_OPINIONS} cluster ids to "
                            "search; one bad id never aborts the batch."
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": (
                            "The literal text to find (statute number, "
                            "doctrine phrase, case short name)."
                        ),
                    },
                    "snippet_size": {
                        "type": "integer",
                        "description": (
                            f"Excerpt window characters, default "
                            f"{GREP_DEFAULT_WIDTH}, at most "
                            f"{GREP_MAX_WIDTH}. Use larger for passages "
                            "with block quotes."
                        ),
                    },
                },
                "required": ["cluster_ids", "query"],
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


def _grep(text: str, query: str, width: int = GREP_DEFAULT_WIDTH) -> list[dict]:
    """Every window of ``text`` around a literal, case-insensitive match.

    The grep-in-opinions primitive: exact-substring matching (not term
    search), returning character offsets so a hit can be followed with a
    targeted read_opinion slice. Capped at GREP_MAX_MATCHES windows;
    overlapping matches inside one window are skipped.
    """
    needle = (query or "").strip().lower()
    if not text or not needle:
        return []
    lower = text.lower()
    matches = []
    pos = lower.find(needle)
    while pos >= 0 and len(matches) < GREP_MAX_MATCHES:
        start = max(0, pos - width // 2)
        end = min(len(text), start + width)
        piece = text[start:end]
        if start > 0:
            piece = "..." + piece
        if end < len(text):
            piece += "..."
        matches.append({"position": pos, "text": piece})
        pos = lower.find(needle, end)
    return matches


def _matter_state(matter) -> str:
    """The jurisdictions.STATES id matching the matter's jurisdiction text."""
    from apps.case.research.jurisdictions import STATES

    jurisdiction = (getattr(matter, "jurisdiction", "") or "").strip().lower()
    if not jurisdiction:
        return ""
    for state in STATES:
        if state["id"] == jurisdiction or state["name"].lower() in jurisdiction:
            return state["id"]
    return ""


def _opinion_for_cluster(cluster_id: int) -> dict | None:
    """Cluster metadata plus the full concatenated opinion text, cached.

    One fetch_cluster call, then every sub-opinion (majority first,
    concurrences and dissents after, same as the research pipeline's
    _get_all_opinion_texts) up to OPINION_TEXT_CAP. Returns None when the
    cluster does not resolve; text may still be empty (old scanned
    opinions). The working set reads this cache and never fetches.
    """
    from apps.case.courtlistener import (
        fetch_cluster,
        fetch_opinion,
        format_citations_with_year,
    )

    cache_key = f"agent_opinion_cluster_{cluster_id}"
    cached = django_cache.get(cache_key)
    if cached is not None:
        return cached

    cluster = fetch_cluster(cluster_id)
    if not cluster:
        return None

    parts = []
    total = 0
    for opinion_url in cluster.get("sub_opinions", []):
        if total >= OPINION_TEXT_CAP:
            break
        try:
            opinion_id = int(opinion_url.rstrip("/").split("/")[-1])
        except (ValueError, IndexError):
            continue
        opinion = fetch_opinion(opinion_id)
        text = opinion.plain_text if opinion.found else ""
        if not text:
            continue
        if parts:
            parts.append(
                "\n\n--- next opinion in this cluster (concurrence or dissent) ---\n\n"
            )
        parts.append(text)
        total += len(text)

    from datetime import date as date_cls

    try:
        date_filed = (
            date_cls.fromisoformat(cluster["date_filed"])
            if cluster.get("date_filed")
            else None
        )
    except ValueError:
        date_filed = None
    payload = {
        "cluster_id": cluster_id,
        "case_name": cluster.get("case_name") or "",
        "citation": format_citations_with_year(
            cluster.get("citations", []), date_filed
        ),
        "date_filed": cluster.get("date_filed") or "",
        "url": (
            f"https://www.courtlistener.com{cluster['absolute_url']}"
            if cluster.get("absolute_url")
            else ""
        ),
        "text": "".join(parts)[:OPINION_TEXT_CAP],
    }
    django_cache.set(cache_key, payload, OPINION_TEXT_CACHE_SECONDS)
    return payload


PENDING_LABELS = {
    "search_materials": 'Searching "{query}"...',
    "read_document": "Reading document {doc_id}...",
    "read_email_thread": "Reading email thread {thread_id}...",
    "read_note": "Reading note {note_id}...",
    "read_caselaw": "Reading saved case {caselaw_id}...",
    "read_conversation": "Reading conversation {conversation_id}...",
    "read_invoice": "Reading invoice {invoice_id}...",
    "read_matter_section": "Reading the {section} section...",
    "search_caselaw": 'Searching case law for "{query}"...',
    "lookup_citation": "Looking up {citation}...",
    "read_opinion": "Reading opinion {cluster_id}...",
    "search_in_opinions": 'Searching opinions for "{query}"...',
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
    from apps.mail.ai import format_email_thread, thread_subject
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

    def _search_scopes(kinds):
        """kind -> (ContentType, scoped pk queryset) for the watson table."""
        from django.contrib.contenttypes.models import ContentType

        from apps.mail.models import Email

        scopes = {}
        if "document" in kinds:
            scopes["document"] = (
                ContentType.objects.get_for_model(Document),
                Document.objects.filter(matter=matter).exclude(ai_context="never"),
            )
        if "highlight" in kinds:
            scopes["highlight"] = (
                ContentType.objects.get_for_model(Highlight),
                Highlight.objects.filter(
                    Q(document__matter=matter) | Q(caselaw__matter=matter)
                ),
            )
        if "fact" in kinds:
            scopes["fact"] = (
                ContentType.objects.get_for_model(Fact),
                Fact.objects.filter(matter=matter),
            )
        note_ct = ContentType.objects.get_for_model(Note)
        if "note" in kinds:
            scopes["note"] = (note_ct, Note.objects.filter(matter=matter).values("pk"))
        if "library" in kinds:
            scopes["library"] = (note_ct, get_library_notes().values("pk"))
        if "email" in kinds:
            scopes["email"] = (
                ContentType.objects.get_for_model(Email),
                Email.objects.filter(matter=matter).exclude(ai_context="never"),
            )
        return scopes

    def _scope_filter(scopes):
        # Join on the text object_id: watson always writes it, while
        # object_id_int stays NULL for BigAutoField primary keys.
        scope_q = Q(pk__in=[])
        for content_type, id_qs in scopes.values():
            ids = [str(pk) for pk in id_qs.values_list("pk", flat=True)]
            scope_q |= Q(content_type=content_type, object_id__in=ids)
        return scope_q

    def _fulltext_entries(query, scopes, cap):
        """websearch_to_tsquery over the watson index, ranked, scoped."""
        from django.db.models import FloatField
        from django.db.models.expressions import RawSQL
        from watson.models import SearchEntry

        return list(
            SearchEntry.objects.filter(_scope_filter(scopes))
            .extra(
                where=[
                    "watson_searchentry.search_tsv @@ "
                    "websearch_to_tsquery('pg_catalog.english', %s)"
                ],
                params=[query],
            )
            .annotate(
                rank=RawSQL(
                    "ts_rank_cd(watson_searchentry.search_tsv, "
                    "websearch_to_tsquery('pg_catalog.english', %s))",
                    (query,),
                    output_field=FloatField(),
                )
            )
            .order_by("-rank")[:cap]
        )

    def _fuzzy_entries(query, scopes, cap):
        """Typo-tolerant fallback: near-miss titles and descriptions by
        trigram word similarity (pg_trgm), when no variant matched."""
        from django.contrib.postgres.search import TrigramWordSimilarity
        from django.db.models.functions import Greatest
        from watson.models import SearchEntry

        return list(
            SearchEntry.objects.filter(_scope_filter(scopes))
            .annotate(
                rank=Greatest(
                    TrigramWordSimilarity(query, "title"),
                    TrigramWordSimilarity(query, "description"),
                )
            )
            .filter(rank__gt=SEARCH_FUZZY_FLOOR)
            .order_by("-rank")[:cap]
        )

    def _entry_hits(entries, scopes, query):
        """SearchEntry rows -> hit dicts (emails grouped by thread)."""
        from apps.mail.models import Email

        def _oid(entry):
            if entry.object_id_int is not None:
                return entry.object_id_int
            try:
                return int(entry.object_id)
            except (TypeError, ValueError):
                return None

        by_ct = {}
        for entry in entries:
            by_ct.setdefault(entry.content_type_id, []).append(entry)
        objects = {}
        loaders = {
            Document: lambda ids: Document.objects.filter(pk__in=ids).defer(
                "ocr_text", "search_vector"
            ),
            Highlight: lambda ids: Highlight.objects.filter(pk__in=ids).select_related(
                "document", "caselaw"
            ),
            Fact: lambda ids: Fact.objects.filter(pk__in=ids),
            Note: lambda ids: Note.objects.filter(pk__in=ids).select_related("folder"),
            Email: lambda ids: Email.objects.filter(pk__in=ids),
        }
        cts = {ct.id: ct for ct, _ in scopes.values()}
        for ct_id, ct_entries in by_ct.items():
            content_type = cts.get(ct_id)
            model = content_type.model_class() if content_type else None
            loader = loaders.get(model)
            if loader is None:
                continue
            ids = [oid for oid in (_oid(e) for e in ct_entries) if oid is not None]
            for obj in loader(ids):
                objects[(ct_id, obj.pk)] = obj

        hits = []
        for entry in entries:
            obj = objects.get((entry.content_type_id, _oid(entry)))
            if obj is None:
                continue
            snippet = _snippet(entry.content or entry.description or "", query)
            rank = float(getattr(entry, "rank", 0) or 0)
            if isinstance(obj, Document):
                hit = {
                    "kind": "document",
                    "id": obj.id,
                    "handle": f"doc:{obj.id}",
                    "name": obj.name,
                    "category": obj.category,
                    "date": str(obj.date) if obj.date else None,
                    "snippet": snippet,
                    "rank": rank,
                }
                if obj.summary:
                    hit["summary"] = obj.summary
                hits.append(hit)
            elif isinstance(obj, Highlight):
                hit = {
                    "kind": "highlight",
                    "id": obj.id,
                    "handle": f"hl:{obj.id}",
                    "name": obj.citation,
                    "category": obj.color,
                    "date": None,
                    "snippet": _snippet(obj.text, query),
                    "rank": rank,
                }
                if obj.document_id:
                    hit["document_id"] = obj.document_id
                    hit["date"] = str(obj.document.date) if obj.document.date else None
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
                        "rank": rank,
                    }
                )
            elif isinstance(obj, Note):
                library = obj.matter_id is None
                hit = {
                    "kind": "library" if library else "note",
                    "id": obj.id,
                    "handle": f"{'lib' if library else 'note'}:{obj.id}",
                    "name": obj.title,
                    "category": (
                        f"Library: {library_folder_path(obj.folder)}"
                        if library
                        else obj.get_category_display()
                    ),
                    "date": (str(obj.updated_at.date()) if obj.updated_at else None),
                    "snippet": _snippet(obj.content or "", query),
                    "rank": rank,
                }
                if library and obj.summary:
                    hit["summary"] = obj.summary
                hits.append(hit)
            else:  # Email -> one hit per thread
                key = obj.thread_id or obj.gmail_id
                hits.append(
                    {
                        "kind": "email",
                        "id": key,
                        "handle": f"thread:{key}",
                        "name": obj.subject or "(no subject)",
                        "category": "Email thread",
                        "date": f"{obj.date:%Y-%m-%d}" if obj.date else None,
                        "snippet": snippet,
                        "rank": rank,
                    }
                )
        return hits

    def _semantic_hits(rows):
        """Semantic rows -> hit dicts shaped like the keyword hits."""
        from apps.mail.models import Email

        loaders = {
            "document": lambda ids: Document.objects.filter(pk__in=ids).defer(
                "ocr_text", "search_vector"
            ),
            "note": lambda ids: Note.objects.filter(pk__in=ids),
            "library": lambda ids: Note.objects.filter(pk__in=ids).select_related(
                "folder"
            ),
            "email": lambda ids: Email.objects.filter(pk__in=ids),
            "highlight": lambda ids: Highlight.objects.filter(
                pk__in=ids
            ).select_related("document", "caselaw"),
            "fact": lambda ids: Fact.objects.filter(pk__in=ids),
        }
        by_kind = {}
        for row in rows:
            by_kind.setdefault(row["kind"], []).append(row["object_id"])
        objects = {}
        for kind, ids in by_kind.items():
            for obj in loaders[kind](ids):
                objects[(kind, obj.pk)] = obj

        hits = []
        for row in rows:
            obj = objects.get((row["kind"], row["object_id"]))
            if obj is None:
                continue
            kind = row["kind"]
            snippet = _snippet(row["text"], row["query"])
            base = {
                "kind": kind,
                "matched": [row["query"]],
                "similarity": row["similarity"],
                "snippet": snippet,
            }
            if kind == "document":
                base.update(
                    id=obj.id,
                    handle=f"doc:{obj.id}",
                    name=obj.name,
                    category=obj.category,
                    date=str(obj.date) if obj.date else None,
                )
                if obj.summary:
                    base["summary"] = obj.summary
            elif kind in ("note", "library"):
                library = obj.matter_id is None
                base["kind"] = "library" if library else "note"
                base.update(
                    id=obj.id,
                    handle=f"{'lib' if library else 'note'}:{obj.id}",
                    name=obj.title,
                    category=(
                        f"Library: {library_folder_path(obj.folder)}"
                        if library
                        else obj.get_category_display()
                    ),
                    date=str(obj.updated_at.date()) if obj.updated_at else None,
                )
                if library and obj.summary:
                    base["summary"] = obj.summary
            elif kind == "email":
                key = obj.thread_id or obj.gmail_id
                base.update(
                    id=key,
                    handle=f"thread:{key}",
                    name=obj.subject or "(no subject)",
                    category="Email thread",
                    date=f"{obj.date:%Y-%m-%d}" if obj.date else None,
                )
            elif kind == "highlight":
                base.update(
                    id=obj.id,
                    handle=f"hl:{obj.id}",
                    name=obj.citation,
                    category=obj.color,
                    date=None,
                )
                if obj.document_id:
                    base["document_id"] = obj.document_id
                elif obj.caselaw_id:
                    base["caselaw_id"] = obj.caselaw_id
            else:  # fact
                base.update(
                    id=obj.id,
                    handle=f"fact:{obj.id}",
                    name=obj.description or "",
                    category="timeline",
                    date=str(obj.date) if obj.date else None,
                )
            hits.append(base)
        return hits

    def _search(tool_input):
        raw = tool_input.get("queries") or []
        if isinstance(raw, str):
            raw = [raw]
        single = str(tool_input.get("query") or "").strip()
        queries = []
        for candidate in ([single] if single else []) + [str(x) for x in raw]:
            candidate = candidate.strip()
            if candidate and candidate.lower() not in [q.lower() for q in queries]:
                queries.append(candidate)
        queries = queries[:SEARCH_MAX_QUERIES]
        if not queries:
            return {"error": "Provide query or queries."}, {}
        kinds = tool_input.get("kinds") or list(SEARCH_KINDS)
        kinds = [k for k in kinds if k in SEARCH_KINDS] or list(SEARCH_KINDS)
        try:
            limit = int(tool_input.get("limit") or SEARCH_DEFAULT_LIMIT)
        except (TypeError, ValueError):
            limit = SEARCH_DEFAULT_LIMIT
        limit = max(1, min(limit, SEARCH_MAX_LIMIT))

        scopes = _search_scopes(kinds)

        merged = {}
        score = {}

        def _fuse(hit_lists, source):
            for hits_list in hit_lists:
                for position, hit in enumerate(hits_list):
                    key = hit["handle"]
                    kept = merged.get(key)
                    if kept is None:
                        hit["matched"] = list(hit.get("matched") or [])
                        hit["_sources"] = {source}
                        merged[key] = hit
                        kept = hit
                    else:
                        kept["_sources"].add(source)
                    for matched_query in hit.get("matched") or []:
                        if matched_query not in kept["matched"]:
                            kept["matched"].append(matched_query)
                    # Reciprocal rank fusion across every list.
                    score[key] = score.get(key, 0.0) + 1.0 / (60 + position)

        keyword_lists = []
        for query in queries:
            hits_list = _entry_hits(
                _fulltext_entries(query, scopes, limit * 2), scopes, query
            )
            for hit in hits_list:
                hit["matched"] = [query]
                hit.pop("rank", None)
            keyword_lists.append(hits_list)
        _fuse(keyword_lists, "keyword")

        semantic_lists = [
            _semantic_hits(rows)
            for rows in semantic_entries(queries, matter, kinds, limit)
        ]
        _fuse(semantic_lists, "semantic")

        fuzzy = False
        if not merged:
            fuzzy = True
            fuzzy_lists = []
            for query in queries:
                hits_list = _entry_hits(
                    _fuzzy_entries(query, scopes, limit), scopes, query
                )
                for hit in hits_list:
                    hit["matched"] = [query]
                    hit["fuzzy"] = True
                    hit.pop("rank", None)
                fuzzy_lists.append(hits_list)
            _fuse(fuzzy_lists, "fuzzy")

        hits = sorted(merged.values(), key=lambda h: -score[h["handle"]])[:limit]
        for hit in hits:
            sources = hit.pop("_sources", set())
            if sources == {"semantic"}:
                # Found by meaning alone: worth the agent knowing the
                # words themselves may not appear in the text.
                hit["semantic"] = True

        seen_count = 0
        with lock:
            for hit in hits:
                key = (hit["kind"], str(hit["id"]))
                hit["seen"] = key in seen_hits
                seen_count += hit["seen"]
                seen_hits.add(key)
        payload = {"queries": queries, "hits": hits, "total": len(hits)}
        if fuzzy:
            payload["note"] = (
                "No exact matches for any variant; these are near matches "
                "by title similarity. Check the names before relying on them."
            )
        elif len(hits) >= 3 and seen_count / len(hits) >= OVERLAP_SHARE:
            payload["note"] = (
                "Most of these hits came back from an earlier search this "
                "turn. Use different terms, or read what you already found."
            )
        more = f" and {len(queries) - 1} more" if len(queries) > 1 else ""
        seen = f", {seen_count} seen before" if seen_count else ""
        fuzz = ", near matches" if fuzzy else ""
        label = (
            f'Searched "{queries[0]}"{more} ({len(hits)} hit'
            f"{'s' if len(hits) != 1 else ''}{seen}{fuzz})"
        )
        return payload, {
            "label": label,
            "title": f'Searched "{queries[0]}"{more}',
            "detail": f"{len(hits)} hits{seen}{fuzz}",
            "query": queries[0],
            "queries": queries,
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
        if doc.description:
            payload["description"] = doc.description
        if doc.summary:
            payload["summary"] = doc.summary
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

    def _search_caselaw(tool_input):
        from apps.case.research.courtlistener import search_opinions
        from apps.case.research.jurisdictions import get_court_ids
        from apps.case.research.tasks import sanitize_query

        raw = tool_input.get("queries") or []
        if isinstance(raw, str):
            raw = [raw]
        single = str(tool_input.get("query") or "").strip()
        queries = []
        for candidate in ([single] if single else []) + [str(x) for x in raw]:
            candidate = candidate.strip()
            if candidate and candidate.lower() not in [q.lower() for q in queries]:
                queries.append(candidate)
        queries = queries[:3]
        if not queries:
            return {"error": "Provide query or queries."}, {}

        state = str(tool_input.get("state") or "").strip().lower() or _matter_state(
            matter
        )
        court = get_court_ids(state, bool(tool_input.get("include_federal")))
        filed_after = str(tool_input.get("filed_after") or "").strip()
        try:
            limit = int(tool_input.get("limit") or CASELAW_SEARCH_DEFAULT_LIMIT)
        except (TypeError, ValueError):
            limit = CASELAW_SEARCH_DEFAULT_LIMIT
        limit = max(1, min(limit, CASELAW_SEARCH_MAX_LIMIT))

        merged = {}
        failed = 0
        for query in queries:
            rows, status = search_opinions(
                sanitize_query(query),
                court=court,
                limit=limit,
                filed_after=filed_after,
            )
            if status != 200:
                failed += 1
                continue
            for row in rows:
                key = row.get("cluster_id") or (
                    f"{row.get('citation')}|{row.get('date_filed')}"
                )
                hit = merged.get(key)
                if hit is None:
                    citations = row.get("citation") or []
                    snippet = (
                        (row.get("snippet") or "")
                        .replace("<mark>", "")
                        .replace("</mark>", "")[:500]
                    )
                    merged[key] = {
                        "case_name": row.get("case_name") or "",
                        "citation": ", ".join(citations),
                        "published": bool(citations),
                        "court": row.get("court") or "",
                        "date_filed": row.get("date_filed") or "",
                        "cluster_id": row.get("cluster_id"),
                        "cite_count": row.get("cite_count") or 0,
                        "snippet": snippet,
                        "matched": [query],
                    }
                elif query not in hit["matched"]:
                    hit["matched"].append(query)

        if failed == len(queries):
            return {
                "error": (
                    "CourtListener search failed for every query "
                    "(API error or no token). Try again or answer from "
                    "the matter's saved case law."
                )
            }, {}

        hits = list(merged.values())
        seen_count = 0
        with lock:
            for hit in hits:
                if not hit["cluster_id"]:
                    continue
                key = ("opinion", str(hit["cluster_id"]))
                hit["seen"] = key in seen_hits
                seen_count += hit["seen"]
                seen_hits.add(key)
        payload = {
            "queries": queries,
            "state": state,
            "hits": hits,
            "total": len(hits),
        }
        if failed:
            payload["note"] = f"{failed} of {len(queries)} queries failed at the API."
        elif len(hits) >= 3 and seen_count / len(hits) >= OVERLAP_SHARE:
            payload["note"] = (
                "Most of these cases came back from an earlier search this "
                "turn. Change WHAT the query asks, or work with the cases "
                "you already found."
            )
        more = f" and {len(queries) - 1} more" if len(queries) > 1 else ""
        label = (
            f'Searched case law "{queries[0]}"{more} ({len(hits)} hit'
            f"{'s' if len(hits) != 1 else ''})"
        )
        return payload, {
            "label": label,
            "title": f'Searched case law "{queries[0]}"{more}',
            "detail": f"{len(hits)} hits",
            "kind": "caselaw_search",
            "query": queries[0],
            "queries": queries,
            "hits": len(hits),
            "chars": 0,
        }

    def _lookup_citation(tool_input):
        from apps.case.courtlistener import lookup_citation

        citation = str(tool_input.get("citation") or "").strip()
        if not citation:
            return {"error": "citation is required."}, {}
        result = lookup_citation(citation)
        if not result.found:
            payload = {
                "found": False,
                "citation": citation,
                "note": (
                    result.error
                    or "No case resolves to this citation on CourtListener."
                ),
            }
            return payload, {
                "label": f"Looked up {citation} (not found)",
                "title": f"Looked up {citation}",
                "detail": "not found",
                "kind": "lookup",
                "id": citation,
                "name": citation,
                "chars": 0,
            }
        payload = {
            "found": True,
            "case_name": result.case_name,
            "citation": result.citation or citation,
            "court": result.court,
            "date_filed": result.date_filed,
            "docket_number": result.docket_number,
            "cluster_id": result.cluster_id,
        }
        return payload, {
            "label": f"Looked up {citation}: {result.case_name}",
            "title": f"Looked up {citation}",
            "detail": result.case_name,
            "kind": "lookup",
            "id": citation,
            "name": result.case_name,
            "chars": 0,
        }

    def _read_opinion(tool_input):
        try:
            cluster_id = int(tool_input.get("cluster_id") or 0)
        except (TypeError, ValueError):
            cluster_id = 0
        if not cluster_id:
            return {"error": "cluster_id is required."}, {}
        data = _opinion_for_cluster(cluster_id)
        if data is None:
            return {
                "error": (
                    f"No CourtListener cluster {cluster_id}, or the fetch failed."
                )
            }, {}
        if not data["text"]:
            return {
                "error": (f"Cluster {cluster_id} has no machine-readable opinion text.")
            }, {}
        fields, chars = _slice(data["text"], tool_input)
        name = data["case_name"] or f"cluster {cluster_id}"
        payload = {
            "cluster_id": cluster_id,
            "case_name": data["case_name"],
            "citation": data["citation"],
            "date_filed": data["date_filed"],
            **fields,
        }
        with lock:
            seen_hits.add(("opinion", str(cluster_id)))
        return payload, {
            "label": _part_label("Read opinion", name, fields),
            "title": f"Read opinion *{name}*",
            "detail": _part_detail(fields),
            "kind": "opinion",
            "id": cluster_id,
            "name": name,
            "chars": chars,
            "total_chars": fields["total_chars"],
        }

    def _grep_opinions(tool_input):
        ids = tool_input.get("cluster_ids") or []
        if not isinstance(ids, list):
            ids = [ids]
        cluster_ids = []
        for raw_id in ids:
            try:
                value = int(raw_id)
            except (TypeError, ValueError):
                continue
            if value and value not in cluster_ids:
                cluster_ids.append(value)
        cluster_ids = cluster_ids[:GREP_MAX_OPINIONS]
        query = str(tool_input.get("query") or "").strip()
        if not cluster_ids or not query:
            return {"error": "Provide cluster_ids and a query."}, {}
        try:
            width = int(tool_input.get("snippet_size") or GREP_DEFAULT_WIDTH)
        except (TypeError, ValueError):
            width = GREP_DEFAULT_WIDTH
        width = max(100, min(width, GREP_MAX_WIDTH))

        results = []
        total_matches = 0
        total_chars = 0
        for cluster_id in cluster_ids:
            try:
                data = _opinion_for_cluster(cluster_id)
            except Exception:  # isolation: one bad id never aborts the batch
                logger.exception("search_in_opinions failed for %s", cluster_id)
                data = None
            if data is None:
                results.append(
                    {
                        "cluster_id": cluster_id,
                        "error": "cluster not found or fetch failed",
                    }
                )
                continue
            if not data["text"]:
                results.append(
                    {
                        "cluster_id": cluster_id,
                        "case_name": data["case_name"],
                        "error": "no machine-readable opinion text",
                    }
                )
                continue
            snippets = _grep(data["text"], query, width)
            total_matches += len(snippets)
            total_chars += sum(len(s["text"]) for s in snippets)
            results.append(
                {
                    "cluster_id": cluster_id,
                    "case_name": data["case_name"],
                    "match_count": len(snippets),
                    "snippets": snippets,
                }
            )
        payload = {"query": query, "results": results}
        n = len(cluster_ids)
        label = (
            f'Searched {n} opinion{"s" if n != 1 else ""} for "{query}" '
            f"({total_matches} match{'es' if total_matches != 1 else ''})"
        )
        return payload, {
            "label": label,
            "title": f'Searched opinions for "{query}"',
            "detail": f"{total_matches} matches in {n} opinions",
            "kind": "opinion_grep",
            "query": query,
            "chars": total_chars,
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
        "search_caselaw": _search_caselaw,
        "lookup_citation": _lookup_citation,
        "read_opinion": _read_opinion,
        "search_in_opinions": _grep_opinions,
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
