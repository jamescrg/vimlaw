"""Tools for the research chat's agentic CourtListener loop.

Provider-neutral: ``build_tools`` emits plain JSON-schema specs that both
the Anthropic and Gemini loops translate; ``make_executor`` returns a
callable the loops invoke per tool call. Tools wrap the existing
CourtListener clients — no new API surface — and every call emits a trail
event that ends up on ``Message.research_trail``.

Budgets are the depth dial: they cap tool calls, result sizes, and the
running total of opinion text fed back into the loop (tool results are
resent every model turn, so the total-chars cap is the token-cost lever).
"""

import json
import logging
from datetime import (
    datetime,
    timezone as dt_timezone,
)

from apps.case.courtlistener import (
    fetch_cluster,
    fetch_opinion,
    format_citations_with_year,
    lookup_citation,
)
from apps.case.models import CaseLaw
from apps.case.research.courtlistener import search_opinions
from apps.case.research.tasks import check_negative_treatment, sanitize_query

logger = logging.getLogger(__name__)

SNIPPET_LIMIT = 500

DEPTH_BUDGETS = {
    "quick": {
        "max_tool_calls": 5,
        "page_size": 4,
        "read_char_cap": 20_000,
        "treatment_tool": False,
        "plan_first": False,
        "total_char_cap": 120_000,
    },
    "standard": {
        "max_tool_calls": 12,
        "page_size": 6,
        "read_char_cap": 30_000,
        "treatment_tool": True,
        "plan_first": False,
        "total_char_cap": 300_000,
    },
    "deep": {
        "max_tool_calls": 25,
        "page_size": 8,
        "read_char_cap": 40_000,
        "treatment_tool": True,
        "plan_first": True,
        "total_char_cap": 600_000,
    },
}


def budget_for(depth):
    return DEPTH_BUDGETS.get(depth, DEPTH_BUDGETS["standard"])


def build_tools(depth):
    """Provider-neutral tool specs (name, description, JSON input schema)."""
    budget = budget_for(depth)
    tools = [
        {
            "name": "search_caselaw",
            "description": (
                "Search CourtListener's opinion database. Returns case name, "
                "citation, court, date, cluster_id, a relevance snippet and "
                "how often each case has been cited. Refine and re-run when "
                "results are off-target."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "CourtListener Solr query, 120 characters or "
                            "fewer. Follow the syntax rules in your "
                            "instructions exactly."
                        ),
                    },
                    "court_ids": {
                        "type": "string",
                        "description": (
                            "Optional space-separated CourtListener court ids "
                            "to restrict the search (e.g. 'gasctapp gactapp "
                            "ca11'). Omit to search all courts."
                        ),
                    },
                    "num_results": {
                        "type": "integer",
                        "description": "How many results to return.",
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "read_opinion",
            "description": (
                "Fetch the full text of an opinion by its cluster_id (from "
                "search results or saved case law). ALWAYS read an opinion "
                "before characterizing its holding or citing it."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "cluster_id": {
                        "type": "integer",
                        "description": "The CourtListener cluster id.",
                    }
                },
                "required": ["cluster_id"],
            },
        },
        {
            "name": "lookup_citation",
            "description": (
                "Resolve an exact reporter citation (e.g. '148 Ga. 616') to "
                "its case. Use this to run down authorities cited inside "
                "opinions you read — the citation network is where thorough "
                "research happens. Returns the case and its cluster_id for "
                "read_opinion."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "citation": {
                        "type": "string",
                        "description": "The reporter citation exactly as written.",
                    }
                },
                "required": ["citation"],
            },
        },
        {
            "name": "list_saved_caselaw",
            "description": (
                "List the case law already saved to this matter from prior "
                "research, with citations, cluster ids and summaries."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "read_library_note",
            "description": (
                "Read the full text of an internal firm library note listed "
                "in the FIRM LIBRARY section (research outlines and practice "
                "guides). Consult relevant library notes early: they record "
                "prior research and often name the controlling authorities. "
                "They are internal work product, never citable authority."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "note_id": {
                        "type": "integer",
                        "description": "The library note id from the FIRM LIBRARY list.",
                    }
                },
                "required": ["note_id"],
            },
        },
    ]
    if budget["treatment_tool"]:
        tools.append(
            {
                "name": "check_treatment",
                "description": (
                    "Check whether later opinions overrule, disapprove, or "
                    "negatively treat a case. Run this on every authority "
                    "your answer relies on."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "cluster_id": {
                            "type": "integer",
                            "description": "The CourtListener cluster id.",
                        }
                    },
                    "required": ["cluster_id"],
                },
            }
        )
    return tools


def _now():
    return datetime.now(dt_timezone.utc).isoformat(timespec="seconds")


def _opinion_for_cluster(cluster_id):
    """cluster -> first sub-opinion -> opinion. Returns (meta, OpinionResult|None)."""
    cluster = fetch_cluster(cluster_id)
    if not cluster:
        return None, None
    sub_opinions = cluster.get("sub_opinions", [])
    try:
        opinion_id = int(sub_opinions[0].rstrip("/").split("/")[-1])
    except (IndexError, ValueError):
        return cluster, None
    return cluster, fetch_opinion(opinion_id)


def make_executor(matter, depth, conversation_id=None):
    """Build the tool executor for one research request.

    Returns ``execute(name, tool_input) -> (result_json_str, trail_event)``.
    Never raises: failures become {"error": ...} results the model can react
    to. Holds per-request state: an opinion cache (re-reads are free), a
    search/lookup dedupe map, and the running opinion-text total against
    the depth's cap. With ``conversation_id``, opinions also cache across
    the conversation's messages (django cache, 1h) so follow-up turns
    re-read earlier authorities without another API round-trip.
    """
    from django.core.cache import cache as django_cache

    budget = budget_for(depth)
    opinion_cache = {}
    library_cache = {}
    state = {"chars_used": 0}
    # Within-run dedupe: the model sometimes repeats a search or lookup it
    # already ran (especially failed ones). Serve the stored result instead
    # of re-hitting the API, and flag the repeat so it shows in the log.
    seen_searches = {}
    seen_lookups = {}

    def _search(tool_input):
        query = sanitize_query(str(tool_input.get("query", ""))[:300])
        court_ids = str(tool_input.get("court_ids", "") or "").strip()
        limit = min(int(tool_input.get("num_results") or budget["page_size"]), 10)

        dedupe_key = (query, court_ids, limit)
        if dedupe_key in seen_searches:
            payload = dict(seen_searches[dedupe_key])
            payload["note"] = (
                "You already ran this exact search in this request; same "
                "results. Adjust the query instead of repeating it."
            )
            event = {
                "type": "search",
                "query": query,
                "court_ids": court_ids,
                "result_count": len(payload.get("results", [])),
                "repeat": True,
                "ts": _now(),
            }
            return payload, event

        results, status = search_opinions(query, court=court_ids or None, limit=limit)
        rows = [
            {
                "case_name": r["case_name"],
                "citation": r["citation"],
                "court": r["court"],
                "date_filed": r["date_filed"],
                "cluster_id": r["cluster_id"],
                "cite_count": r.get("cite_count"),
                "snippet": (r.get("snippet") or "")[:SNIPPET_LIMIT],
            }
            for r in results
        ]
        payload = {"results": rows}
        if status != 200:
            payload["error"] = f"Search failed (status {status}). Adjust the query."
        seen_searches[dedupe_key] = payload
        event = {
            "type": "search",
            "query": query,
            "court_ids": court_ids,
            "result_count": len(rows),
            "results": [
                {"case_name": r["case_name"], "cluster_id": r["cluster_id"]}
                for r in rows
            ],
            "ts": _now(),
        }
        return payload, event

    def _conv_cache_key(cluster_id):
        return f"research_opinion_{conversation_id}_{cluster_id}"

    def _read(tool_input):
        cluster_id = int(tool_input.get("cluster_id") or 0)
        if cluster_id in opinion_cache:
            cached = opinion_cache[cluster_id]
            event = {
                "type": "read",
                "cluster_id": cluster_id,
                "case_name": cached.get("case_name", ""),
                "cached": True,
                "ts": _now(),
            }
            return cached, event

        if state["chars_used"] >= budget["total_char_cap"]:
            return {
                "error": (
                    "Research reading budget exhausted. Answer from the "
                    "opinions you have already read."
                )
            }, None

        # Read earlier in this conversation (a previous message's run)?
        if conversation_id:
            stored = django_cache.get(_conv_cache_key(cluster_id))
            if stored:
                state["chars_used"] += len(stored.get("text", ""))
                opinion_cache[cluster_id] = stored
                event = {
                    "type": "read",
                    "cluster_id": cluster_id,
                    "case_name": stored.get("case_name", ""),
                    "citation": stored.get("citation", ""),
                    "cached": True,
                    "ts": _now(),
                }
                return stored, event

        cluster, opinion = _opinion_for_cluster(cluster_id)
        if cluster is None or opinion is None or not opinion.found:
            return {"error": f"Opinion for cluster {cluster_id} not available."}, None

        text = (opinion.plain_text or "")[: budget["read_char_cap"]]
        state["chars_used"] += len(text)
        citation = format_citations_with_year(
            cluster.get("citations", []), None
        ) or cluster.get("citation_string", "")
        payload = {
            "case_name": cluster.get("case_name", ""),
            "citation": citation,
            "court": cluster.get("court", ""),
            "date_filed": cluster.get("date_filed", ""),
            "cluster_id": cluster_id,
            "text": text,
            "truncated": len(opinion.plain_text or "") > len(text),
        }
        opinion_cache[cluster_id] = payload
        if conversation_id:
            django_cache.set(_conv_cache_key(cluster_id), payload, timeout=3600)
        event = {
            "type": "read",
            "cluster_id": cluster_id,
            "case_name": payload["case_name"],
            "citation": citation,
            "chars": len(text),
            "ts": _now(),
        }
        return payload, event

    def _treatment(tool_input):
        cluster_id = int(tool_input.get("cluster_id") or 0)
        known = opinion_cache.get(cluster_id, {})
        outcome = check_negative_treatment(
            cluster_id, known.get("case_name", ""), known.get("citation", "")
        )
        event = {
            "type": "treatment",
            "cluster_id": cluster_id,
            "case_name": known.get("case_name", ""),
            "has_negative_treatment": outcome["has_negative_treatment"],
            "reason": outcome["reason"],
            "checked": outcome["checked"],
            "ts": _now(),
        }
        return outcome, event

    def _lookup(tool_input):
        citation = str(tool_input.get("citation", "")).strip()
        if citation in seen_lookups:
            payload = dict(seen_lookups[citation])
            payload["note"] = (
                "You already looked this citation up in this request; same result."
            )
            event = {
                "type": "lookup",
                "citation": citation,
                "found": payload.get("found", False),
                "case_name": payload.get("case_name", ""),
                "cluster_id": payload.get("cluster_id"),
                "repeat": True,
                "ts": _now(),
            }
            return payload, event
        result = lookup_citation(citation)
        payload = {
            "found": result.found,
            "case_name": result.case_name,
            "citation": result.citation or citation,
            "court": result.court,
            "date_filed": result.date_filed,
            "cluster_id": result.cluster_id,
        }
        if not result.found:
            payload["error"] = result.error or "Citation not found."
        seen_lookups[citation] = payload
        event = {
            "type": "lookup",
            "citation": citation,
            "found": result.found,
            "case_name": result.case_name,
            "cluster_id": result.cluster_id,
            "ts": _now(),
        }
        return payload, event

    def _library_read(tool_input):
        from apps.case.ai.selector import library_folder_path
        from apps.notes.models import get_library_notes

        note_id = int(tool_input.get("note_id") or 0)
        if note_id in library_cache:
            cached = library_cache[note_id]
            event = {
                "type": "library_read",
                "note_id": note_id,
                "title": cached.get("title", ""),
                "cached": True,
                "ts": _now(),
            }
            return cached, event

        if state["chars_used"] >= budget["total_char_cap"]:
            return {
                "error": (
                    "Research reading budget exhausted. Answer from the "
                    "material you have already read."
                )
            }, None

        note = get_library_notes().select_related("folder").filter(pk=note_id).first()
        if note is None or not note.content:
            return {
                "error": f"Library note {note_id} not found or not in the AI library."
            }, None

        text = note.content[: budget["read_char_cap"]]
        state["chars_used"] += len(text)
        payload = {
            "note_id": note_id,
            "title": note.title,
            "folder": library_folder_path(note.folder),
            "text": text,
            "truncated": len(note.content) > len(text),
        }
        library_cache[note_id] = payload
        event = {
            "type": "library_read",
            "note_id": note_id,
            "title": note.title,
            "chars": len(text),
            "truncated": payload["truncated"],
            "ts": _now(),
        }
        return payload, event

    def _saved(tool_input):
        rows = [
            {
                "case_name": c.case_name,
                "citation": c.citation,
                "court": c.court,
                "date_filed": str(c.date_filed or ""),
                "cluster_id": c.cluster_id,
                "summary": (c.summary or "")[:400],
                "importance": c.importance,
            }
            for c in CaseLaw.objects.filter(matter=matter)
        ]
        event = {"type": "saved", "count": len(rows), "ts": _now()}
        return {"cases": rows}, event

    handlers = {
        "search_caselaw": _search,
        "read_opinion": _read,
        "check_treatment": _treatment,
        "lookup_citation": _lookup,
        "list_saved_caselaw": _saved,
        "read_library_note": _library_read,
    }

    def execute(name, tool_input):
        handler = handlers.get(name)
        if handler is None:
            return json.dumps({"error": f"Unknown tool {name!r}."}), None
        try:
            payload, event = handler(tool_input or {})
        except Exception:
            logger.exception("Research tool %s failed", name)
            payload, event = {"error": f"Tool {name} failed; try differently."}, None
        return json.dumps(payload, default=str), event

    return execute
