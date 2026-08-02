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


def make_executor(matter, depth):
    """Build the tool executor for one research request.

    Returns ``execute(name, tool_input) -> (result_json_str, trail_event)``.
    Never raises: failures become {"error": ...} results the model can react
    to. Holds per-request state: an opinion cache (re-reads are free) and
    the running opinion-text total against the depth's cap.
    """
    budget = budget_for(depth)
    opinion_cache = {}
    state = {"chars_used": 0}

    def _search(tool_input):
        query = sanitize_query(str(tool_input.get("query", ""))[:300])
        court_ids = str(tool_input.get("court_ids", "") or "").strip()
        limit = min(int(tool_input.get("num_results") or budget["page_size"]), 10)
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
        event = {
            "type": "lookup",
            "citation": citation,
            "found": result.found,
            "case_name": result.case_name,
            "cluster_id": result.cluster_id,
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
