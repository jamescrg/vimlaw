"""Tools for the research chat's agentic CourtListener loop.

Provider-neutral: ``build_tools`` emits plain JSON-schema specs that both
the Anthropic and Gemini loops translate; ``make_executor`` returns a
callable the loops invoke per tool call. Tools wrap the existing
CourtListener clients — no new API surface — and every call emits a trail
event that ends up on ``Message.research_trail``.

Budgets are the effort dial: they cap tool calls, result sizes, and the
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

# Hard ceiling on results per search. The default page size is the effort level's
# page_size; the model may ask for more (up to this cap) when a survey needs
# more. Result rows are resent every model turn, so the cap bounds cost.
MAX_SEARCH_RESULTS = 20

# Cap on the editorial syllabus/headnotes text a skim injects. Skims are
# the survey lane: wide triage at a fraction of a read's token cost.
SKIM_CHAR_LIMIT = 2_000

# The abstractor reads the ENTIRE opinion (this is only a runaway guard,
# matching the treatment checker's full-read cap) and returns a short
# structured brief, so the loop carries ~2k chars per case instead of a
# 30k truncated slice. Mirrors how an attorney works: read everything,
# outline the holding and its bearing on the matter, brief the file.
ABSTRACT_READ_CAP = 250_000

ABSTRACT_SYSTEM = """\
You are a careful legal research assistant briefing a case for an
attorney's outline. You are given a QUESTION PRESENTED and the FULL text
of one judicial opinion. Write a compact abstract with these sections:

CASE: name, citation, court, date.
POSTURE: procedural posture in one line.
VEHICLE: the exact statutory or procedural basis of the decision (the
statute AND subsection, rule, or motion type the court decided under).
If it differs from the vehicle the question presented implies, say so
here and again under CAUTIONS: a case decided under a different
subsection or motion type is not authority for this question without an
explicit distinction.
HOLDING: the holding(s), each with a VERBATIM quotation of the court's
operative language in quotation marks. Never paraphrase inside quotes.
RELEVANCE: how the reasoning bears on the question presented, citing the
specific passages (quote the key sentences verbatim).
CAUTIONS: anything that limits the case (dicta, distinguishable facts,
partial dissents, later history noted in the text).
SCOPE: one line listing other issues the opinion covers, so the reader
knows what else is in it.

Under 400 words plus quotations. If the opinion is genuinely irrelevant
to the question, say so in one line under RELEVANCE and keep the rest
minimal."""

EFFORT_BUDGETS = {
    "low": {
        "max_searches": 3,
        "max_tool_calls": 4,
        "max_skims": 8,
        "page_size": 6,
        "read_char_cap": 20_000,
        "treatment_tool": False,
        "plan_first": False,
        "total_char_cap": 120_000,
    },
    # Three pools per run: searches, skims, and study calls (reads,
    # briefs, treatment checks, lookups). Searches were split into their
    # own capped pool 2026-08-15 after runs 892/898/899 kept burning the
    # shared budget on rephrased queries and starving treatment checks -
    # the overlap guard dampened but never stopped the looping, so the
    # search tool now simply runs dry. Medium/high raised same day after
    # the CourtListener Tier 3 upgrade (20/min, 250/hour, 1,000/day).
    # CL requests per tool call: search 1, read_opinion 2 (cluster +
    # opinion; conversation-cached repeats 0), check_treatment up to ~11,
    # library reads 0 — the loop's model turns space them naturally and the
    # throttle's 429 backoff absorbs bursts. total_char_cap stays the token
    # cost lever: tool results are resent every model turn.
    "medium": {
        "max_searches": 7,
        "max_tool_calls": 12,
        "max_skims": 20,
        "page_size": 8,
        "read_char_cap": 30_000,
        "treatment_tool": True,
        "plan_first": False,
        "total_char_cap": 450_000,
    },
    "high": {
        "max_searches": 12,
        "max_tool_calls": 25,
        "max_skims": 40,
        "page_size": 10,
        "read_char_cap": 40_000,
        "treatment_tool": True,
        "plan_first": True,
        "total_char_cap": 900_000,
    },
}


def budget_for(effort):
    return EFFORT_BUDGETS.get(effort, EFFORT_BUDGETS["medium"])


def build_tools(effort):
    """Provider-neutral tool specs (name, description, JSON input schema)."""
    budget = budget_for(effort)
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
                        "description": (
                            "How many results to return (up to "
                            f"{MAX_SEARCH_RESULTS}). Ask for more than the "
                            "default when surveying a broad doctrine — one "
                            "deep result list beats several near-identical "
                            "queries."
                        ),
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "find_citing_cases",
            "description": (
                "Forward citation search: find later cases that cite a given "
                "case. Use this to get from an old or seminal case to the "
                "current controlling statement of its rule, to see how a "
                "doctrine developed, or to test whether an authority is "
                "still being followed. Optionally filter the citing cases "
                "with query terms."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "cluster_id": {
                        "type": "integer",
                        "description": "The CourtListener cluster id of the cited case.",
                    },
                    "query": {
                        "type": "string",
                        "description": (
                            "Optional search terms to filter the citing "
                            "cases (same syntax as search_caselaw). Omit to "
                            "see the most relevant citing cases overall."
                        ),
                    },
                    "court_ids": {
                        "type": "string",
                        "description": (
                            "Optional space-separated CourtListener court ids "
                            "to restrict the search. Omit to search all courts."
                        ),
                    },
                    "num_results": {
                        "type": "integer",
                        "description": (
                            f"How many results to return (up to {MAX_SEARCH_RESULTS})."
                        ),
                    },
                },
                "required": ["cluster_id"],
            },
        },
        {
            "name": "read_opinion",
            "description": (
                "Fetch the text of an opinion by its cluster_id (from "
                "search results or saved case law). ALWAYS read an opinion "
                "before characterizing its holding or citing it. Long "
                "opinions come back truncated as beginning + END (holdings "
                "and dispositions live at the end) with the omitted middle "
                "marked; request specific parts when the omitted analysis "
                "matters."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "cluster_id": {
                        "type": "integer",
                        "description": "The CourtListener cluster id.",
                    },
                    "part": {
                        "type": "integer",
                        "description": (
                            "Optional: fetch one contiguous slice of a long "
                            "opinion (2, 3, ...) as numbered in a truncated "
                            "read's omission marker. Omit for the normal "
                            "beginning-plus-end read."
                        ),
                    },
                },
                "required": ["cluster_id"],
            },
        },
        {
            "name": "abstract_opinion",
            "description": (
                "The default way to study a shortlisted case: a briefing "
                "agent reads the ENTIRE opinion (no truncation) and returns "
                "a structured abstract - holding with VERBATIM quotes, "
                "relevance to the question presented, cautions, and scope. "
                "Costs a fraction of read_opinion in your context. Prefer "
                "this for every shortlisted case; use read_opinion only "
                "when you must study exact language at length (e.g. "
                "reconciling conflicting authorities)."
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
            "name": "skim_cluster",
            "description": (
                "Cheap triage: fetch a case's metadata and editorial "
                "syllabus/headnotes (when available) WITHOUT the full "
                "opinion text. Skims draw on their own, larger budget - "
                "use them to survey many candidates from search results "
                "before spending full reads on the few that matter. A "
                "skim is NOT a read: never characterize a holding or cite "
                "a case from a skim alone; read_opinion the finalists."
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


def make_executor(matter, effort, conversation_id=None, question=""):
    """Build the tool executor for one research request.

    Returns ``execute(name, tool_input) -> (result_json_str, trail_event)``.
    Never raises: failures become {"error": ...} results the model can react
    to. Holds per-request state: an opinion cache (re-reads are free), a
    search/lookup dedupe map, and the running opinion-text total against
    the effort level's cap; ``question`` is the user's question presented,
    given to the abstractor. With ``conversation_id``, opinions also cache across
    the conversation's messages (django cache, 1h) so follow-up turns
    re-read earlier authorities without another API round-trip.
    """
    from django.core.cache import cache as django_cache

    budget = budget_for(effort)
    opinion_cache = {}
    library_cache = {}
    skim_cache = {}
    abstract_cache = {}
    state = {"chars_used": 0, "calls_used": 0, "skims_used": 0, "searches_used": 0}
    # Within-run dedupe: the model sometimes repeats a search or lookup it
    # already ran (especially failed ones). Serve the stored result instead
    # of re-hitting the API, and flag the repeat so it shows in the log.
    seen_searches = {}
    seen_lookups = {}
    # Every cluster_id any search has returned. Lets follow-up searches be
    # scored for redundancy: a query whose results were mostly seen before
    # gets told so, and repeat offenses get their repeated rows WITHHELD
    # (conversation 898 showed the polite note alone being ignored) - only
    # genuinely new results come back, so rephrasing buys nothing.
    seen_result_ids = set()
    overlap_strikes = [0]

    def _run_query(query, court_ids, limit, event_type, event_extra=None):
        """Shared body of search_caselaw and find_citing_cases: dedupe,
        query CourtListener, shape rows, emit the trail event."""
        dedupe_key = (query, court_ids, limit)
        if dedupe_key in seen_searches:
            payload = dict(seen_searches[dedupe_key])
            payload["note"] = (
                "You already ran this exact search in this request; same "
                "results. Adjust the query instead of repeating it."
            )
            event = {
                "type": event_type,
                "query": query,
                "court_ids": court_ids,
                "result_count": len(payload.get("results", [])),
                "repeat": True,
                "ts": _now(),
                **(event_extra or {}),
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
        overlap = sum(1 for r in rows if r["cluster_id"] in seen_result_ids)
        fresh = [r for r in rows if r["cluster_id"] not in seen_result_ids]
        seen_result_ids.update(r["cluster_id"] for r in rows)
        suppressed = False
        if rows and overlap >= max(2, (len(rows) * 3) // 5):
            overlap_strikes[0] += 1
            if overlap_strikes[0] >= 2:
                # Second offense onward: withhold the repeated rows.
                suppressed = True
                payload["results"] = fresh
                payload["note"] = (
                    f"{overlap} of {len(rows)} results were already returned "
                    "by your earlier searches and have been WITHHELD; only "
                    f"the {len(fresh)} new result(s) are shown. Rephrasing "
                    "the same concepts returns the same cases. Change a "
                    "concept, triage the results you already have, or re-run "
                    "one earlier query with a larger num_results."
                )
            else:
                payload["note"] = (
                    f"{overlap} of {len(rows)} results already appeared in "
                    "your earlier searches - this query mostly re-covered "
                    "old ground. Change a concept (not the phrasing), triage "
                    "the results you already have, or re-run one query with "
                    "a larger num_results."
                )
        seen_searches[dedupe_key] = payload
        event = {
            "type": event_type,
            "query": query,
            "court_ids": court_ids,
            "result_count": len(rows),
            "overlap_count": overlap,
            "suppressed": suppressed,
            "results": [
                {"case_name": r["case_name"], "cluster_id": r["cluster_id"]}
                for r in rows
            ],
            "ts": _now(),
            **(event_extra or {}),
        }
        return payload, event

    def _search(tool_input):
        query = sanitize_query(str(tool_input.get("query", ""))[:300])
        court_ids = str(tool_input.get("court_ids", "") or "").strip()
        limit = min(
            int(tool_input.get("num_results") or budget["page_size"]),
            MAX_SEARCH_RESULTS,
        )
        return _run_query(query, court_ids, limit, "search")

    def _citing(tool_input):
        cluster_id = int(tool_input.get("cluster_id") or 0)
        if not cluster_id:
            return {"error": "find_citing_cases needs a cluster_id."}, None
        filter_terms = sanitize_query(str(tool_input.get("query", "") or "")[:300])
        court_ids = str(tool_input.get("court_ids", "") or "").strip()
        limit = min(
            int(tool_input.get("num_results") or budget["page_size"]),
            MAX_SEARCH_RESULTS,
        )
        # cites:() is composed tool-side so the model never writes fielded
        # queries itself (the syntax rules forbid them).
        query = f"cites:({cluster_id})"
        if filter_terms:
            query += f" AND ({filter_terms})"
        known = opinion_cache.get(cluster_id, {})
        return _run_query(
            query,
            court_ids,
            limit,
            "citing",
            event_extra={
                "cluster_id": cluster_id,
                "case_name": known.get("case_name", ""),
            },
        )

    def _conv_cache_key(cluster_id):
        return f"research_opinion_{conversation_id}_{cluster_id}"

    def _read(tool_input):
        cluster_id = int(tool_input.get("cluster_id") or 0)
        requested_part = int(tool_input.get("part") or 0)
        if requested_part <= 1 and cluster_id in opinion_cache:
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
        # Part reads bypass both caches: they fetch a specific slice.
        if conversation_id and requested_part <= 1:
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

        full = opinion.plain_text or ""
        cap = budget["read_char_cap"]
        total_parts = max(1, -(-len(full) // cap))
        citation = format_citations_with_year(
            cluster.get("citations", []), None
        ) or cluster.get("citation_string", "")

        if requested_part > 1:
            # Explicit continuation: a contiguous cap-sized slice.
            text = full[cap * (requested_part - 1) : cap * requested_part]
            if not text:
                return {
                    "error": (
                        f"Opinion has no part {requested_part}: it is "
                        f"{len(full):,} characters ({total_parts} parts)."
                    )
                }, None
        elif len(full) <= cap:
            text = full
        else:
            # Default read of a long opinion: beginning AND end, because
            # holdings and dispositions live at the end. The omitted middle
            # stays reachable via part reads.
            head = (cap * 2) // 3
            tail = cap - head
            omitted = len(full) - head - tail
            text = (
                full[:head]
                + f"\n\n[... {omitted:,} characters omitted from the MIDDLE "
                f"of this opinion. The beginning and the END are included "
                f"above and below this marker. To read omitted text, call "
                f"read_opinion with part=2..{total_parts} (each part is a "
                f"contiguous {cap:,}-character slice of the full opinion). "
                f"...]\n\n" + full[-tail:]
            )
        state["chars_used"] += len(text)
        payload = {
            "case_name": cluster.get("case_name", ""),
            "citation": citation,
            "court": cluster.get("court", ""),
            "date_filed": cluster.get("date_filed", ""),
            "cluster_id": cluster_id,
            "text": text,
            "truncated": len(full) > cap,
            "length_chars": len(full),
            "parts": total_parts,
        }
        if requested_part > 1:
            payload["part"] = requested_part
        else:
            # Only the default (head+tail) read is cached and reused.
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
        if requested_part > 1:
            event["part"] = requested_part
        return payload, event

    def _abstract(tool_input):
        from .gemini_client import send_to_gemini

        cluster_id = int(tool_input.get("cluster_id") or 0)
        if not cluster_id:
            return {"error": "abstract_opinion needs a cluster_id."}, None
        if cluster_id in abstract_cache:
            cached = dict(abstract_cache[cluster_id])
            cached["note"] = "Already abstracted in this request."
            event = {
                "type": "abstract",
                "cluster_id": cluster_id,
                "case_name": cached.get("case_name", ""),
                "citation": cached.get("citation", ""),
                "cached": True,
                "ts": _now(),
            }
            return cached, event

        if state["chars_used"] >= budget["total_char_cap"]:
            return {
                "error": (
                    "Research reading budget exhausted. Answer from the "
                    "material you already have."
                )
            }, None

        cluster, opinion = _opinion_for_cluster(cluster_id)
        if cluster is None or opinion is None or not opinion.found:
            return {"error": f"Opinion for cluster {cluster_id} not available."}, None

        full = (opinion.plain_text or "")[:ABSTRACT_READ_CAP]
        citation = format_citations_with_year(
            cluster.get("citations", []), None
        ) or cluster.get("citation_string", "")
        header = (
            f"{cluster.get('case_name', '')}, {citation} "
            f"({cluster.get('court', '')} {cluster.get('date_filed', '')})"
        )
        try:
            abstract_text, _, _ = send_to_gemini(
                system_context=ABSTRACT_SYSTEM,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"QUESTION PRESENTED: {question or 'not stated'}\n\n"
                            f"OPINION: {header}\n\n{full}"
                        ),
                    }
                ],
                model="gemini-2.5-flash",
            )
        except Exception:
            logger.exception("Abstractor failed for cluster %s", cluster_id)
            return {
                "error": (
                    "The abstractor failed for this opinion; use read_opinion instead."
                )
            }, None

        state["chars_used"] += len(abstract_text)
        payload = {
            "cluster_id": cluster_id,
            "case_name": cluster.get("case_name", ""),
            "citation": citation,
            "court": cluster.get("court", ""),
            "date_filed": cluster.get("date_filed", ""),
            "abstract": abstract_text,
            "opinion_chars_read": len(full),
        }
        abstract_cache[cluster_id] = payload
        event = {
            "type": "abstract",
            "cluster_id": cluster_id,
            "case_name": payload["case_name"],
            "citation": citation,
            "abstract": abstract_text,
            "opinion_chars_read": len(full),
            "ts": _now(),
        }
        return payload, event

    def _skim(tool_input):
        from django.utils.html import strip_tags

        cluster_id = int(tool_input.get("cluster_id") or 0)
        if not cluster_id:
            return {"error": "skim_cluster needs a cluster_id."}, None
        if cluster_id in skim_cache:
            cached = dict(skim_cache[cluster_id])
            cached["note"] = "Already skimmed this cluster in this request."
            event = {
                "type": "skim",
                "cluster_id": cluster_id,
                "case_name": cached.get("case_name", ""),
                "citation": cached.get("citation", ""),
                "has_syllabus": bool(cached.get("syllabus")),
                "cached": True,
                "ts": _now(),
            }
            return cached, event

        cluster = fetch_cluster(cluster_id)
        if not cluster:
            return {"error": f"Cluster {cluster_id} not available."}, None
        citation = format_citations_with_year(
            cluster.get("citations", []), None
        ) or cluster.get("citation_string", "")
        summary_text = ""
        for field in ("syllabus", "headnotes", "summary", "headmatter"):
            value = strip_tags(str(cluster.get(field) or "")).strip()
            if value:
                summary_text = value[:SKIM_CHAR_LIMIT]
                break
        state["chars_used"] += len(summary_text)
        payload = {
            "cluster_id": cluster_id,
            "case_name": cluster.get("case_name", ""),
            "citation": citation,
            "court": cluster.get("court", ""),
            "date_filed": cluster.get("date_filed", ""),
            "syllabus": summary_text or None,
        }
        if not summary_text:
            payload["note"] = (
                "No editorial summary on this cluster; metadata only. "
                "read_opinion it if the metadata looks on point."
            )
        skim_cache[cluster_id] = payload
        event = {
            "type": "skim",
            "cluster_id": cluster_id,
            "case_name": payload["case_name"],
            "citation": citation,
            "has_syllabus": bool(summary_text),
            "ts": _now(),
        }
        return payload, event

    def _treatment(tool_input):
        cluster_id = int(tool_input.get("cluster_id") or 0)
        # The case may be known from a full read, a brief, or a skim.
        known = (
            opinion_cache.get(cluster_id)
            or abstract_cache.get(cluster_id)
            or skim_cache.get(cluster_id)
            or {}
        )
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
        "find_citing_cases": _citing,
        "read_opinion": _read,
        "abstract_opinion": _abstract,
        "skim_cluster": _skim,
        "check_treatment": _treatment,
        "lookup_citation": _lookup,
        "list_saved_caselaw": _saved,
        "read_library_note": _library_read,
    }

    def execute(name, tool_input):
        handler = handlers.get(name)
        if handler is None:
            return json.dumps({"error": f"Unknown tool {name!r}."}), None
        # Three-pool call accounting: searches, skims, and study calls
        # (reads, briefs, treatment checks, lookups). The provider loop's
        # own ceiling is the sum of all pools, as a backstop.
        if name in ("search_caselaw", "find_citing_cases"):
            if state["searches_used"] >= budget["max_searches"]:
                return json.dumps(
                    {
                        "error": (
                            f"Search budget exhausted "
                            f"({budget['max_searches']} searches). Study "
                            "what you already have: skim, brief, or read "
                            "the results your searches returned, or answer."
                        )
                    }
                ), None
            state["searches_used"] += 1
        elif name == "skim_cluster":
            if state["skims_used"] >= budget["max_skims"]:
                return json.dumps(
                    {
                        "error": (
                            "Skim budget exhausted. Read your strongest "
                            "candidates in full or answer."
                        )
                    }
                ), None
            state["skims_used"] += 1
        else:
            if state["calls_used"] >= budget["max_tool_calls"]:
                return json.dumps(
                    {
                        "error": (
                            "Study budget exhausted. Provide your best "
                            "answer from the opinions already read."
                        )
                    }
                ), None
            state["calls_used"] += 1
        try:
            payload, event = handler(tool_input or {})
        except Exception:
            logger.exception("Research tool %s failed", name)
            payload, event = {"error": f"Tool {name} failed; try differently."}, None
        return json.dumps(payload, default=str), event

    return execute
