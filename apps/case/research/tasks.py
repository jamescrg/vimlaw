"""Background task for processing research queries."""

import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from apps.case.ai.gemini_client import send_to_gemini
from apps.case.courtlistener import (
    API_V4_URL,
    fetch_cluster,
    fetch_opinion,
    get_api_token,
    lookup_citation,
)
from apps.case.courtlistener_throttle import throttled_request
from apps.case.research.query_syntax import (
    COURTLISTENER_SYNTAX_RULES,
    QUERY_DESIGN_RULES,
)

from .briefing import (
    PROCEDURAL_VEHICLE_RULES,
    RESEARCH_ABSTRACT_SYSTEM,
    parse_brief,
)
from .courtlistener import (
    get_forward_citations,
    search_opinions,
)
from .jurisdictions import get_court_ids
from .models import CaseBrief, CitationVerification, ResearchQuery, ResearchResult

logger = logging.getLogger(__name__)

# Per-run pipeline budgets. Two searches (relevance page + newest-first
# slice of the same approved query), full-opinion briefs for the strongest
# candidates, then bounded citation chasing from the HIGH briefs. Roughly
# 45 CourtListener requests per typical run, spaced by the throttle.
SEARCH_PRIMARY_LIMIT = 20
SEARCH_DATE_LIMIT = 10
BRIEF_MAX = 15
BRIEF_OPINION_CHAR_CAP = 250_000
CITING_SEED_MAX = 2
CITING_RESULT_LIMIT = 10
CITING_BRIEF_MAX = 4
CHASE_AUTHORITY_MAX = 4
# The answer is the product; briefs stay on the flash default.
ANSWER_MODEL = "gemini-pro-latest"


def refine_research_query(query_id):
    """Run query refinement in a background daemon thread, then pause for user review."""
    thread = threading.Thread(target=_refine_and_pause, args=(query_id,), daemon=True)
    thread.start()


def process_research_query(query_id):
    """Run search + processing in a background daemon thread (after user confirms)."""
    thread = threading.Thread(target=_process_query, args=(query_id,), daemon=True)
    thread.start()


def sanitize_query(query):
    """Validate and fix common CourtListener query syntax issues.

    Returns the sanitized query string.
    """
    # Fix word~N (invalid: fuzzy doesn't take integer distance).
    # word~ is valid (fuzzy), "phrase"~N is valid (proximity).
    # Match bare word (not after a closing quote) followed by ~N
    query = re.sub(r'(?<!")~(\d+)', "~", query)

    # Fix unbalanced parentheses
    depth = 0
    for ch in query:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                # More closing than opening — strip this excess
                break
    if depth > 0:
        query += ")" * depth
    elif depth < 0:
        # Remove excess closing parens from the end
        while depth < 0 and query.endswith(")"):
            query = query[:-1]
            depth += 1

    # Fix unbalanced quotes — append a closing quote if odd count
    if query.count('"') % 2 != 0:
        query += '"'

    # Remove fielded searches (e.g. court_id:xxx) — court filtering is separate
    query = re.sub(r"\b\w+_id:\S+", "", query)

    # Collapse multiple spaces
    query = re.sub(r"  +", " ", query).strip()

    return query


def _refine_query(query_id):
    """Use AI to convert natural language query into structured search syntax."""
    ResearchQuery.objects.filter(pk=query_id).update(status="refining")

    query = ResearchQuery.objects.get(pk=query_id)

    system_prompt = (
        "You are a legal research strategist. Your job is to understand what the user "
        "is really trying to find out, identify the core legal issue, and then craft a "
        "CourtListener search query that will surface the most relevant case law.\n\n"
        "STEP 1 — Understand the question:\n"
        "- What is the user trying to determine? What legal issue or principle is at stake?\n"
        "- What kind of cases would actually answer this question?\n"
        "- Think about the legal doctrines, standards, and tests that courts apply here.\n\n"
        "STEP 2 — Design the query:\n"
        "- Target the legal concepts and doctrines that relevant cases would discuss, "
        "not just the keywords from the user's question.\n"
        "- Include the legal terminology courts actually use when addressing this issue.\n"
        "- Think about what holdings, standards, or tests a relevant opinion would contain.\n\n"
        + COURTLISTENER_SYNTAX_RULES
        + QUERY_DESIGN_RULES
        + PROCEDURAL_VEHICLE_RULES
        + "Example input: Can a joint tenant with right of survivorship file an "
        "equitable partition suit?\n"
        'Example output: ("joint tenancy" OR "joint tenant") '
        'AND "right of survivorship" AND ("equitable partition" OR partition) '
        'AND (suit OR action OR "cause of action")\n\n'
        "Return ONLY the search query string, nothing else."
    )
    user_prompt = query.query_text

    try:
        response_text, _, _ = send_to_gemini(
            system_prompt, [{"role": "user", "content": user_prompt}]
        )
        structured = response_text.strip().strip("`").strip()
        structured = sanitize_query(structured)
        ResearchQuery.objects.filter(pk=query_id).update(structured_query=structured)
    except Exception:
        logger.exception("Error refining query %s, using raw text", query_id)
        ResearchQuery.objects.filter(pk=query_id).update(
            structured_query=query.query_text
        )


def _refine_and_pause(query_id):
    """Refine the query with AI, then pause for user review."""
    try:
        _refine_query(query_id)
        ResearchQuery.objects.filter(pk=query_id).update(status="refined")
    except Exception:
        logger.exception("Error refining research query %s", query_id)
        ResearchQuery.objects.filter(pk=query_id).update(
            status="error", error_message="An error occurred while refining the query."
        )


def _process_query(query_id):
    """Process a research query: search CourtListener and store results."""
    try:
        query = ResearchQuery.objects.get(pk=query_id)
    except ResearchQuery.DoesNotExist:
        return

    try:
        ResearchQuery.objects.filter(pk=query_id).update(status="searching")

        search_text = query.structured_query or query.query_text
        court = get_court_ids(query.state, query.include_federal)

        results, status_code = search_opinions(
            search_text, court=court, limit=SEARCH_PRIMARY_LIMIT
        )

        # If the structured query caused a server error, retry with raw query text
        if not results and status_code == 500 and query.structured_query:
            logger.warning(
                "Structured query failed for %s, retrying with raw text", query_id
            )
            results, status_code = search_opinions(
                query.query_text, court=court, limit=SEARCH_PRIMARY_LIMIT
            )

        if not results:
            if status_code == 500:
                msg = "CourtListener returned an error. The search query may be too complex."
            elif status_code != 200:
                msg = f"CourtListener search failed (status {status_code})."
            else:
                msg = "No results found on CourtListener."
            ResearchQuery.objects.filter(pk=query_id).update(
                status="error", error_message=msg
            )
            return

        # Newest-first slice of the SAME approved query. CL's relevance
        # score disfavors very recent opinions with empty citation graphs
        # (slip opinions especially), so a date-ordered page rescues what
        # the score-ordered page never surfaces. Failure is non-fatal.
        date_results, date_status = search_opinions(
            search_text,
            court=court,
            limit=SEARCH_DATE_LIMIT,
            order_by="dateFiled desc",
        )
        if date_status != 200:
            date_results = []

        # Deduplicate by cluster_id and by citation + date_filed, keeping
        # track of which search surfaced each row.
        candidates = [(r, "search") for r in results] + [
            (r, "date") for r in date_results
        ]
        seen_clusters = set()
        seen_citations = set()
        unique_results = []
        for result, source in candidates:
            cid = result.get("cluster_id")
            if cid and cid in seen_clusters:
                continue

            citation = result.get("citation", [])
            date_filed = result.get("date_filed", "")
            cite_str = str(citation) + "|" + date_filed
            if citation and cite_str in seen_citations:
                continue

            if cid:
                seen_clusters.add(cid)
            if citation:
                seen_citations.add(cite_str)
            unique_results.append((result, source))

        # Create result records
        for i, (result, source) in enumerate(unique_results, 1):
            citation_list = result.get("citation", [])
            citation_str = (
                ", ".join(citation_list)
                if isinstance(citation_list, list)
                else str(citation_list)
            )

            ResearchResult.objects.create(
                query_id=query_id,
                position=i,
                case_name=result.get("case_name", ""),
                citation=citation_str,
                court=result.get("court", ""),
                date_filed=result.get("date_filed", ""),
                cluster_id=result.get("cluster_id"),
                snippet=result.get("snippet", ""),
                score=result.get("score"),
                forward_citation_count=result.get("cite_count"),
                courtlistener_url=result.get("courtlistener_url", ""),
                relevance="pending",
                status_message="Evaluating...",
                source=source,
            )

        # ── Phase 2: Snippet Triage (Pass 1) ──
        ResearchQuery.objects.filter(pk=query_id).update(status="processing")

        result_records = list(
            ResearchResult.objects.filter(query_id=query_id).order_by("position")
        )

        triage_results = {}
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(_triage_by_snippet, r, query.query_text): r
                for r in result_records
            }
            for future in as_completed(futures):
                r = futures[future]
                try:
                    triage_results[r.id] = future.result()
                except Exception:
                    triage_results[r.id] = (True, "")

        # Rejected rows are kept (relevance="rejected", reason stored) so
        # the ruled-out list stays inspectable - a wrongly-triaged case
        # used to vanish without a trace.
        for rid, (proceed, reason) in triage_results.items():
            if not proceed:
                ResearchResult.objects.filter(pk=rid).update(
                    relevance="rejected",
                    eval_reason=reason,
                    status_message="Ruled out at triage",
                )

        # ── Phase 3: Full-opinion briefing ──
        survivors = list(
            ResearchResult.objects.filter(
                query_id=query_id, relevance="pending"
            ).order_by("position")
        )
        # Newest-first rows get guaranteed brief slots: CL's relevance
        # ranking already had its say in the primary ordering, and the
        # date slice exists precisely to rescue opinions it disfavors.
        survivors.sort(key=lambda r: (r.source != "date", r.position))
        to_brief = survivors[:BRIEF_MAX]
        overflow = survivors[BRIEF_MAX:]
        if overflow:
            ResearchResult.objects.filter(pk__in=[r.id for r in overflow]).update(
                relevance="none", status_message="Not briefed (run cap)"
            )

        if to_brief:
            ResearchResult.objects.filter(pk__in=[r.id for r in to_brief]).update(
                status_message="Fetching opinion..."
            )

            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {
                    executor.submit(_brief_result, r, query.query_text): r
                    for r in to_brief
                }
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception:
                        r = futures[future]
                        logger.exception("Error briefing result %s", r.id)
                        ResearchResult.objects.filter(pk=r.id).update(
                            relevance="error", status_message="Briefing failed"
                        )

        # ── Phase 4: Reorder (nothing is deleted; ruled-out rows sink) ──
        _reorder_results(query_id)

    except Exception:
        logger.exception("Error processing research query %s", query_id)
        ResearchQuery.objects.filter(pk=query_id).update(
            status="error", error_message="An unexpected error occurred."
        )
        return

    _run_enrichment(query_id)


def _add_new_results(query, rows, source, via_case):
    """Create rows for chase hits not already in this run.

    Returns the created (pending) results; rows whose cluster is already
    present are skipped silently.
    """
    existing = set(
        ResearchResult.objects.filter(query_id=query.id).values_list(
            "cluster_id", flat=True
        )
    )
    next_position = ResearchResult.objects.filter(query_id=query.id).count()
    created = []
    for row in rows:
        cid = row.get("cluster_id")
        if not cid or cid in existing:
            continue
        existing.add(cid)
        next_position += 1
        citation_list = row.get("citation", [])
        citation_str = (
            ", ".join(citation_list)
            if isinstance(citation_list, list)
            else str(citation_list)
        )
        created.append(
            ResearchResult.objects.create(
                query_id=query.id,
                position=next_position,
                case_name=row.get("case_name", ""),
                citation=citation_str,
                court=row.get("court", ""),
                date_filed=row.get("date_filed", ""),
                cluster_id=cid,
                snippet=row.get("snippet", ""),
                score=row.get("score"),
                forward_citation_count=row.get("cite_count"),
                courtlistener_url=row.get("courtlistener_url", ""),
                relevance="pending",
                status_message="Found by citation chase...",
                source=source,
                via_case=via_case,
            )
        )
    return created


def _chase_citing_cases(query, court):
    """Forward chase: search cases citing the strongest HIGH results.

    A brand-new opinion applying the controlling rule is nearly invisible
    to keyword relevance ranking but appears immediately in a
    forward-citation search from the line's seminal cases - this is how a
    slip opinion gets found. The cites:() query is composed tool-side
    (never model-written, so it skips sanitize_query).
    """
    seeds = list(
        ResearchResult.objects.filter(query_id=query.id, relevance="high").order_by(
            "-forward_citation_count", "position"
        )
    )[:CITING_SEED_MAX]
    created = []
    for seed in seeds:
        if not seed.cluster_id:
            continue
        rows, status = search_opinions(
            f"cites:({seed.cluster_id})", court=court, limit=CITING_RESULT_LIMIT
        )
        if status != 200:
            continue
        created += _add_new_results(query, rows, "citing", seed.case_name)
    return created


def _chase_key_authorities(query):
    """Backward chase: resolve the reporter citations the HIGH briefs say
    their holdings rest on, and pull in any the run hasn't seen. Capped
    at CHASE_AUTHORITY_MAX lookup attempts."""
    from .courtlistener import COURTLISTENER_BASE_URL

    seen_cites = set()
    attempts = 0
    created = []
    highs = ResearchResult.objects.filter(query_id=query.id, relevance="high")
    for result in highs:
        for cite in result.key_authorities or []:
            normalized = " ".join(cite.split()).lower()
            if normalized in seen_cites:
                continue
            seen_cites.add(normalized)
            if attempts >= CHASE_AUTHORITY_MAX:
                return created
            attempts += 1
            lookup = lookup_citation(cite)
            if not lookup.found or not lookup.cluster_id:
                continue
            url = (
                f"{COURTLISTENER_BASE_URL}{lookup.absolute_url}"
                if lookup.absolute_url
                else ""
            )
            created += _add_new_results(
                query,
                [
                    {
                        "case_name": lookup.case_name,
                        "citation": lookup.citation or cite,
                        "court": lookup.court,
                        "date_filed": str(lookup.date_filed or ""),
                        "cluster_id": lookup.cluster_id,
                        "courtlistener_url": url,
                    }
                ],
                "authority",
                result.case_name,
            )
    return created


def _run_enrichment(query_id):
    """Citation chasing, treatment checks, and the final answer."""
    try:
        query = ResearchQuery.objects.get(pk=query_id)
    except ResearchQuery.DoesNotExist:
        return

    try:
        ResearchQuery.objects.filter(pk=query_id).update(status="enriching")
        court = get_court_ids(query.state, query.include_federal)

        citing_rows = _chase_citing_cases(query, court)
        citing_rows.sort(key=lambda r: -(r.forward_citation_count or 0))
        to_brief = citing_rows[:CITING_BRIEF_MAX]
        skipped = citing_rows[CITING_BRIEF_MAX:]
        if skipped:
            ResearchResult.objects.filter(pk__in=[r.id for r in skipped]).update(
                relevance="none", status_message="Not briefed (run cap)"
            )
        # Authority rows are already capped hard; brief them all.
        to_brief += _chase_key_authorities(query)

        if to_brief:
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {
                    executor.submit(_brief_result, r, query.query_text): r
                    for r in to_brief
                }
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception:
                        r = futures[future]
                        logger.exception("Error briefing result %s", r.id)
                        ResearchResult.objects.filter(pk=r.id).update(
                            relevance="error", status_message="Briefing failed"
                        )

        _reorder_results(query_id)

        # ── Negative History Check (every HIGH row, chased ones included) ──
        high_results = list(
            ResearchResult.objects.filter(query_id=query_id, relevance="high").order_by(
                "position"
            )
        )
        if high_results:
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {
                    executor.submit(_check_negative_history, r): r for r in high_results
                }
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception:
                        r = futures[future]
                        logger.exception(
                            "Error checking negative history for result %s", r.id
                        )

        # ── Final Answer ──
        ResearchQuery.objects.filter(pk=query_id).update(status="synthesizing")
        _generate_final_answer(query_id)

    except Exception:
        logger.exception("Error enriching research query %s", query_id)
        ResearchQuery.objects.filter(pk=query_id).update(
            status="error", error_message="An unexpected error occurred."
        )


def summarize_result(result_id):
    """Run on-demand summarization of a single result in a background thread."""
    thread = threading.Thread(target=_summarize_result, args=(result_id,), daemon=True)
    thread.start()


def _summarize_result(result_id):
    """On-demand briefing of a single result (the Brief-case button):
    same full-opinion path the pipeline uses."""
    try:
        result = ResearchResult.objects.select_related("query").get(pk=result_id)
    except ResearchResult.DoesNotExist:
        return

    ResearchResult.objects.filter(pk=result_id).update(
        relevance="pending", status_message="Briefing..."
    )

    try:
        question = result.query.query_text if result.query_id else ""
        _brief_result(result, question)
    except Exception:
        logger.exception("Error briefing result %s", result_id)
        ResearchResult.objects.filter(pk=result_id).update(
            relevance="error", status_message="Briefing failed"
        )


def _triage_by_snippet(result, query_text):
    """Pass 1: quick relevance check using only the search snippet.

    Returns (proceed, reason). Slip opinions often have no snippet at all
    (no editorial syllabus), so an empty snippet always proceeds.
    """
    if not result.snippet:
        return True, ""

    system_prompt = (
        "You are a legal research assistant performing a quick relevance triage. "
        "Respond ONLY with valid JSON."
    )
    user_prompt = (
        f"Based on the search snippet below, determine if this case is potentially "
        f"relevant to the research query. Be INCLUSIVE — only mark as skip if the case "
        f"is clearly unrelated to the legal issue being researched.\n\n"
        f"Research Query: {query_text}\n\n"
        f"Case: {result.case_name}\n"
        f"Court: {result.court}\n"
        f"Date Filed: {result.date_filed}\n\n"
        f"Search Snippet:\n{result.snippet[:2000]}\n\n"
        f'Respond with JSON: {{"proceed": true or false, "reason": "one sentence"}}'
    )

    try:
        response_text, _, _ = send_to_gemini(
            system_prompt, [{"role": "user", "content": user_prompt}]
        )
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(cleaned)
        return parsed.get("proceed", True), str(parsed.get("reason", ""))
    except Exception:
        logger.exception("Snippet triage error for result %s", result.id)
        return True, ""


def _reorder_results(query_id):
    """Renumber positions: strong cases first, ruled-out rows at the end."""
    relevance_order = {
        "high": 0,
        "medium": 1,
        "error": 2,
        "none": 3,
        "pending": 3,
        "low": 4,
        "rejected": 5,
    }
    final_results = list(
        ResearchResult.objects.filter(query_id=query_id).order_by("position")
    )
    final_results.sort(key=lambda r: (relevance_order.get(r.relevance, 3), r.position))
    for i, result in enumerate(final_results, 1):
        if result.position != i:
            ResearchResult.objects.filter(pk=result.id).update(position=i)


def _get_all_opinion_texts(cluster_id, cap=BRIEF_OPINION_CHAR_CAP):
    """Concatenated plain text of EVERY opinion in a cluster, up to cap.

    The majority opinion comes first (CourtListener lists it first);
    concurrences and dissents follow with separators. The old
    single-opinion read was blind to holdings outside sub_opinions[0].
    """
    cluster = fetch_cluster(cluster_id)
    if not cluster:
        return ""

    parts = []
    total = 0
    for opinion_url in cluster.get("sub_opinions", []):
        if total >= cap:
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

    return "".join(parts)[:cap]


def _brief_result(result, question):
    """Brief one case from its FULL opinion text.

    The briefing agent reads the entire cluster (every sub-opinion, capped
    only against freak 500-page opinions) and returns the structured
    abstract; parse_brief maps its verdict onto the relevance field.
    Replaces the old 8,000-character excerpt evaluation, which scored
    syllabus-less slip opinions low because it never reached the holding.
    """
    result_id = result.id

    if not result.cluster_id:
        ResearchResult.objects.filter(pk=result_id).update(
            relevance="error", status_message="No cluster ID"
        )
        return

    ResearchResult.objects.filter(pk=result_id).update(
        status_message="Downloading opinion..."
    )

    opinion_text = _get_all_opinion_texts(result.cluster_id)
    if not opinion_text:
        ResearchResult.objects.filter(pk=result_id).update(
            relevance="error", status_message="Could not fetch opinion text"
        )
        return

    ResearchResult.objects.filter(pk=result_id).update(
        opinion_text=opinion_text[:50000],
        status_message="Briefing...",
    )

    citation = result.citation or "no reporter citation (slip opinion)"
    header = f"{result.case_name}, {citation} ({result.court} {result.date_filed})"
    user_prompt = (
        f"QUESTION PRESENTED: {question}\n\nOPINION: {header}\n\n{opinion_text}"
    )

    try:
        response_text, _, _ = send_to_gemini(
            RESEARCH_ABSTRACT_SYSTEM, [{"role": "user", "content": user_prompt}]
        )
    except Exception:
        logger.exception("Briefing failed for result %s", result_id)
        ResearchResult.objects.filter(pk=result_id).update(
            relevance="error", status_message="Briefing failed"
        )
        return

    brief_text = response_text.strip()
    parsed = parse_brief(brief_text)
    ResearchResult.objects.filter(pk=result_id).update(
        brief=brief_text,
        relevance=parsed["verdict"],
        eval_reason=parsed["reason"],
        key_authorities=parsed["key_authorities"],
        status_message="Complete",
    )


# Treatment-check tuning. Depth is CourtListener's per-citing-opinion count
# of how many times it cites the case: a depth-1 citer is a single passing
# citation, and no court overrules or disapproves a case in one mention, so
# those are skipped entirely. Among substantial citers we read the FULL
# opinion text (capped only to keep a freak 500-page opinion bounded) —
# disapproval buried past an excerpt window was the old check's blind spot.
TREATMENT_MIN_DEPTH = 2
TREATMENT_MAX_READS = 5
TREATMENT_CANDIDATE_POOL = 12
TREATMENT_OPINION_CHAR_CAP = 250_000

TREATMENT_SYSTEM_PROMPT = (
    "You are a legal research assistant assessing how a citing opinion "
    "treats a cited case. Respond ONLY with valid JSON."
)


def _classify_treatment(case_name, citation, citing):
    """Ask Flash how one citing opinion treats the cited case.

    Returns {"treatment": "negative"|"good_law"|"neutral", "reason": str}.
    """
    text = citing["text"][:TREATMENT_OPINION_CHAR_CAP]
    truncated = " ... (opinion continues)" if len(citing["text"]) > len(text) else ""
    user_prompt = (
        f"The opinion below cites {case_name} ({citation}).\n"
        f"Read the ENTIRE opinion and classify its treatment of the cited case:\n"
        f'- "negative": it overrules, abrogates, disapproves, limits, '
        f"questions, or otherwise negatively treats the cited case, anywhere "
        f"in the text (including in passing or in a footnote).\n"
        f'- "good_law": it affirmatively follows, applies, or relies on the '
        f"cited case as good law.\n"
        f'- "neutral": it merely mentions or distinguishes the cited case '
        f"without endorsing or undermining it.\n\n"
        f"Citing opinion ({citing['name']}, {citing['date'] or 'date unknown'}):\n"
        f"{text}{truncated}\n\n"
        f'Respond with JSON: {{"treatment": "negative" | "good_law" | '
        f'"neutral", "reason": "one sentence explanation"}}'
    )
    response_text, _, _ = send_to_gemini(
        TREATMENT_SYSTEM_PROMPT, [{"role": "user", "content": user_prompt}]
    )
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    parsed = json.loads(cleaned)
    treatment = parsed.get("treatment", "neutral")
    if treatment not in ("negative", "good_law", "neutral"):
        treatment = "neutral"
    return {"treatment": treatment, "reason": parsed.get("reason", "")}


def check_negative_treatment(cluster_id, case_name="", citation=""):
    """Pure negative-treatment check against substantial forward citations.

    Returns {"checked": bool, "has_negative_treatment": bool, "reason": str}.
    checked=False means the chain couldn't be evaluated (no cluster/opinion);
    no forward citations at all counts as checked with no negative treatment.
    Shared by the research pipeline and the research chat's check_treatment
    tool.

    Method: take the most-cited-by citing opinions (CourtListener depth =
    how many times each citing opinion cites the case), drop single-mention
    citers, then read the full text of up to TREATMENT_MAX_READS of them in
    most-recent-first order. A negative verdict returns immediately; a
    citing case that affirmatively treats the case as good law also stops
    the walk — everything older predates that endorsement, so it can't
    change the currency verdict. Only neutral mentions keep the walk going.
    """
    if not cluster_id:
        return {"checked": False, "has_negative_treatment": False, "reason": ""}

    cluster = fetch_cluster(cluster_id)
    sub_opinions = cluster.get("sub_opinions", []) if cluster else []
    if not sub_opinions:
        return {"checked": False, "has_negative_treatment": False, "reason": ""}

    try:
        opinion_id = int(sub_opinions[0].rstrip("/").split("/")[-1])
    except (ValueError, IndexError):
        return {"checked": False, "has_negative_treatment": False, "reason": ""}

    forward_cites = get_forward_citations(opinion_id, limit=TREATMENT_CANDIDATE_POOL)
    if not forward_cites:
        return {
            "checked": True,
            "has_negative_treatment": False,
            "reason": "No citing opinions found.",
        }

    substantial = [
        cite for cite in forward_cites if cite.get("depth", 0) >= TREATMENT_MIN_DEPTH
    ][:TREATMENT_MAX_READS]
    if not substantial:
        return {
            "checked": True,
            "has_negative_treatment": False,
            "reason": (
                "Only passing citations found (each citing opinion cites the "
                "case once); no substantial treatment to evaluate."
            ),
        }

    # Read each substantial citer in full and collect its case name + filing
    # date so the walk can run most-recent-first.
    candidates = []
    for cite in substantial:
        citing_opinion = fetch_opinion(cite["citing_opinion_id"])
        if not citing_opinion.found or not citing_opinion.plain_text:
            continue
        name = ""
        date_filed = ""
        if citing_opinion.cluster_id:
            citing_cluster = fetch_cluster(citing_opinion.cluster_id) or {}
            name = citing_cluster.get("case_name", "")
            date_filed = str(citing_cluster.get("date_filed") or "")
        candidates.append(
            {
                "name": name or f"opinion {cite['citing_opinion_id']}",
                "date": date_filed,
                "depth": cite.get("depth", 0),
                "text": citing_opinion.plain_text,
            }
        )

    if not candidates:
        return {
            "checked": True,
            "has_negative_treatment": False,
            "reason": "Citing opinions could not be read.",
        }

    # Most recent first; undated citers go last.
    candidates.sort(key=lambda c: c["date"] or "0000-00-00", reverse=True)

    neutral_seen = 0
    for citing in candidates:
        verdict = _classify_treatment(case_name, citation, citing)
        label = f"{citing['name']} ({citing['date'] or 'date unknown'})"
        if verdict["treatment"] == "negative":
            return {
                "checked": True,
                "has_negative_treatment": True,
                "reason": f"{label}: {verdict['reason']}",
            }
        if verdict["treatment"] == "good_law":
            return {
                "checked": True,
                "has_negative_treatment": False,
                "reason": (
                    f"Treated as good law by {label}; no newer substantial "
                    f"citer disapproves it, so older citers were not read."
                ),
            }
        neutral_seen += 1

    return {
        "checked": True,
        "has_negative_treatment": False,
        "reason": (
            f"No negative treatment found in the {neutral_seen} most "
            f"substantial citing opinions (read in full, most recent first)."
        ),
    }


def _check_negative_history(result):
    """Quick check for negative treatment in top forward citations."""
    try:
        outcome = check_negative_treatment(
            result.cluster_id, result.case_name, result.citation
        )
    except Exception:
        logger.exception("Error checking negative history for result %s", result.id)
        return
    if outcome["checked"]:
        ResearchResult.objects.filter(pk=result.id).update(
            has_negative_history=outcome["has_negative_treatment"]
        )


def _generate_final_answer(query_id):
    """Answer the research question from the FULL briefs of the high cases.

    Runs on the pro model - the answer is the run's product; everything
    upstream stays on the flash default. Completes without a summary when
    nothing rated high.
    """
    query = ResearchQuery.objects.get(pk=query_id)
    high_results = list(
        ResearchResult.objects.filter(query_id=query_id, relevance="high")
        .exclude(brief="")
        .order_by("position")
    )

    if not high_results:
        ResearchQuery.objects.filter(pk=query_id).update(status="complete")
        ResearchResult.objects.filter(query_id=query_id).update(opinion_text="")
        return

    blocks = []
    for r in high_results:
        citation = r.citation or "no reporter citation - slip opinion"
        cites = (
            f"cited {r.forward_citation_count} times"
            if r.forward_citation_count
            else "no citing history yet"
        )
        if r.has_negative_history is True:
            treatment = "NEGATIVE treatment detected in citing cases"
        elif r.has_negative_history is False:
            treatment = "treatment checked: no negative treatment found"
        else:
            treatment = "treatment not checked"
        blocks.append(
            f"CASE: {r.case_name}\n"
            f"CITATION: {citation}\n"
            f"COURT: {r.court} ({r.date_filed})\n"
            f"CITING HISTORY: {cites}\n"
            f"TREATMENT: {treatment}\n"
            f"BRIEF:\n{r.brief}"
        )

    system_prompt = (
        "You are a legal research assistant writing up the results of a "
        "case-law search for an attorney. You are given the research "
        "question and the full structured briefs of the relevant cases. "
        "Write the answer as follows:\n"
        "1. ANSWER FIRST: a direct answer to the question in a short "
        "paragraph, stating the controlling rule and its exact statutory "
        "or procedural vehicle (statute AND subsection, rule, or motion "
        "type).\n"
        "2. Then discuss each case under its own heading, UNDER 200 "
        "WORDS per case: what it holds (quote the operative language "
        "from its brief verbatim) and how it bears on the question.\n"
        "3. Match authorities to the question's procedural vehicle: a "
        "case whose VEHICLE section shows a different subsection or "
        "motion type must be excluded or explicitly distinguished, "
        "never blended in.\n"
        "4. Flag every slip opinion or case with no citing history as "
        "new and not yet settled law, and note any case marked "
        "'treatment not checked' or carrying negative treatment.\n"
        "5. Cite ONLY the cases provided. If the briefs do not answer "
        "the question, say so plainly instead of stretching them."
    )
    user_prompt = f"RESEARCH QUESTION: {query.query_text}\n\n" + "\n\n---\n\n".join(
        blocks
    )

    try:
        response_text, _, _ = send_to_gemini(
            system_prompt,
            [{"role": "user", "content": user_prompt}],
            model=ANSWER_MODEL,
        )

        ResearchQuery.objects.filter(pk=query_id).update(
            status="complete", final_summary=response_text.strip()
        )

    except Exception:
        logger.exception("Error generating final answer for query %s", query_id)
        ResearchQuery.objects.filter(pk=query_id).update(status="complete")

    # Clean up opinion text to save space
    ResearchResult.objects.filter(query_id=query_id).update(opinion_text="")


def review_result(result_id):
    """Run citation review in a background daemon thread."""
    thread = threading.Thread(target=_review_result, args=(result_id,), daemon=True)
    thread.start()


def review_more_citations(result_id):
    """Evaluate more unevaluated forward citations in a background thread."""
    thread = threading.Thread(
        target=_review_more_citations, args=(result_id,), daemon=True
    )
    thread.start()


def _review_result(result_id):
    """Fetch forward citations by depth, generate case summary, assess top 5."""
    try:
        result = ResearchResult.objects.get(pk=result_id)
    except ResearchResult.DoesNotExist:
        return

    ResearchResult.objects.filter(pk=result_id).update(verify_status="verifying")

    try:
        if not result.cluster_id:
            ResearchResult.objects.filter(pk=result_id).update(verify_status="error")
            return

        # Get opinion_id from cluster
        cluster = fetch_cluster(result.cluster_id)
        if not cluster:
            ResearchResult.objects.filter(pk=result_id).update(verify_status="error")
            return

        sub_opinions = cluster.get("sub_opinions", [])
        if not sub_opinions:
            ResearchResult.objects.filter(pk=result_id).update(verify_status="error")
            return

        try:
            opinion_id = int(sub_opinions[0].rstrip("/").split("/")[-1])
        except (ValueError, IndexError):
            ResearchResult.objects.filter(pk=result_id).update(verify_status="error")
            return

        # Generate 150-word case summary
        opinion = fetch_opinion(opinion_id)
        if opinion.found:
            _generate_review_summary(result_id, result, opinion.plain_text)

        # Fetch forward citations (top 20 by depth)
        forward_cites = get_forward_citations(opinion_id, limit=20)
        if not forward_cites:
            ResearchResult.objects.filter(pk=result_id).update(verify_status="complete")
            return

        # Create CitationVerification records for all with metadata
        for i, cite in enumerate(forward_cites, 1):
            citing_id = cite["citing_opinion_id"]
            citing_meta = _get_opinion_metadata(citing_id)

            CitationVerification.objects.create(
                result_id=result_id,
                position=i,
                case_name=citing_meta.get("case_name", ""),
                citation=citing_meta.get("citation", ""),
                court=citing_meta.get("court", ""),
                date_filed=citing_meta.get("date_filed", ""),
                cluster_id=citing_meta.get("cluster_id"),
                courtlistener_url=citing_meta.get("courtlistener_url", ""),
                depth=cite["depth"],
                summary="",
            )

        # Assess top 5 by depth
        top_verifications = CitationVerification.objects.filter(
            result_id=result_id
        ).order_by("position")[:5]
        _assess_citations(result, top_verifications)

        ResearchResult.objects.filter(pk=result_id).update(verify_status="complete")

    except Exception:
        logger.exception("Error reviewing result %s", result_id)
        ResearchResult.objects.filter(pk=result_id).update(verify_status="error")


def _generate_review_summary(result_id, result, opinion_text):
    """Generate a 150-word case summary for the Review tab."""
    truncated = opinion_text[:8000]
    system_prompt = "You are a legal research assistant. Write clear, concise prose."
    user_prompt = (
        f"Write a 150-word summary of this case. Focus on the key facts, "
        f"the legal issue, and the court's holding.\n\n"
        f"Case: {result.case_name}\n"
        f"Court: {result.court}\n"
        f"Date: {result.date_filed}\n\n"
        f"Opinion Text (excerpt):\n{truncated}"
    )

    try:
        response_text, _, _ = send_to_gemini(
            system_prompt, [{"role": "user", "content": user_prompt}]
        )
        ResearchResult.objects.filter(pk=result_id).update(
            review_summary=response_text.strip()
        )
    except Exception:
        logger.exception("Error generating review summary for result %s", result_id)


def _assess_citations(result, verifications):
    """Generate AI treatment summaries for a set of CitationVerification records."""
    query_text = result.query.query_text if result.query_id else ""

    for v in verifications:
        if not v.cluster_id:
            continue

        # Get opinion_id from cluster
        cluster = fetch_cluster(v.cluster_id)
        if not cluster:
            continue
        sub_opinions = cluster.get("sub_opinions", [])
        if not sub_opinions:
            continue
        try:
            citing_opinion_id = int(sub_opinions[0].rstrip("/").split("/")[-1])
        except (ValueError, IndexError):
            continue

        citing_opinion = fetch_opinion(citing_opinion_id)
        if not citing_opinion.found:
            continue

        truncated = citing_opinion.plain_text[:8000]
        system_prompt = (
            "You are a legal research assistant. Respond ONLY with valid JSON."
        )
        context = f"Research Query: {query_text}\n" if query_text else ""
        user_prompt = (
            f"This opinion cites {result.case_name}. Analyze how this citing opinion "
            f"treats the cited case.\n\n"
            f"{context}"
            f"Original Case: {result.case_name} ({result.citation})\n\n"
            f"Citing Opinion Text (excerpt):\n{truncated}\n\n"
            f'Respond with JSON: {{"treatment": "positive/negative/neutral/distinguished",'
            f' "summary": "2-3 sentence summary of how this opinion treats the cited case"}}'
        )

        treatment = "neutral"
        summary = ""
        try:
            response_text, _, _ = send_to_gemini(
                system_prompt, [{"role": "user", "content": user_prompt}]
            )
            cleaned = response_text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            parsed = json.loads(cleaned)
            treatment = parsed.get("treatment", "neutral")
            if treatment not in ("positive", "negative", "neutral", "distinguished"):
                treatment = "neutral"
            summary = parsed.get("summary", "")
        except Exception:
            logger.exception("Error summarizing forward citation %s", v.id)
            summary = "Could not analyze treatment."

        CitationVerification.objects.filter(pk=v.id).update(
            treatment=treatment, summary=summary
        )


def assess_single_citation(verification_id):
    """Assess a single citation in a background thread."""
    thread = threading.Thread(
        target=_assess_single_citation, args=(verification_id,), daemon=True
    )
    thread.start()


def _assess_single_citation(verification_id):
    """Assess a single CitationVerification record."""
    try:
        v = CitationVerification.objects.select_related("result").get(
            pk=verification_id
        )
    except CitationVerification.DoesNotExist:
        return

    try:
        _assess_citations(v.result, [v])
    except Exception:
        logger.exception("Error assessing citation %s", verification_id)


def _review_more_citations(result_id):
    """Assess the next batch of unevaluated forward citations."""
    try:
        result = ResearchResult.objects.get(pk=result_id)
    except ResearchResult.DoesNotExist:
        return

    ResearchResult.objects.filter(pk=result_id).update(verify_status="verifying")

    try:
        unassessed = CitationVerification.objects.filter(
            result_id=result_id, summary=""
        ).order_by("position")[:5]

        if unassessed:
            _assess_citations(result, unassessed)

        ResearchResult.objects.filter(pk=result_id).update(verify_status="complete")
    except Exception:
        logger.exception("Error reviewing more citations for result %s", result_id)
        ResearchResult.objects.filter(pk=result_id).update(verify_status="complete")


def _get_opinion_metadata(opinion_id):
    """Fetch basic metadata for an opinion via its cluster."""
    try:
        api_token = get_api_token()
        if not api_token:
            return {}

        response = throttled_request(
            "get",
            f"{API_V4_URL}/opinions/{opinion_id}/",
            headers={"Authorization": f"Token {api_token}"},
            timeout=30,
        )
        if response.status_code != 200:
            return {}

        data = response.json()
        cluster_url = data.get("cluster", "")
        try:
            cluster_id = int(cluster_url.rstrip("/").split("/")[-1])
        except (ValueError, IndexError):
            return {}

        cluster = fetch_cluster(cluster_id)
        if not cluster:
            return {}

        date_filed = cluster.get("date_filed", "")
        case_name = cluster.get("case_name", "")
        absolute_url = cluster.get("absolute_url", "")

        # Build citation string
        citations = cluster.get("citations", [])
        cite_parts = []
        for c in citations:
            v = c.get("volume", "")
            r = c.get("reporter", "")
            p = c.get("page", "")
            if v and r and p:
                cite_parts.append(f"{v} {r} {p}")
        citation = ", ".join(cite_parts)

        return {
            "case_name": case_name,
            "citation": citation,
            "court": cluster.get("court", ""),
            "date_filed": date_filed,
            "cluster_id": cluster_id,
            "courtlistener_url": (
                f"https://www.courtlistener.com{absolute_url}" if absolute_url else ""
            ),
        }

    except Exception:
        logger.exception("Error fetching opinion metadata for %s", opinion_id)
        return {}


def generate_caselaw_summary(caselaw_id):
    """Generate a 200-word AI summary for a CaseLaw entry in a background thread."""
    thread = threading.Thread(
        target=_generate_caselaw_summary, args=(caselaw_id,), daemon=True
    )
    thread.start()


def _generate_caselaw_summary(caselaw_id):
    """Fetch opinion text and generate a 200-word summary."""
    from apps.case.models import CaseLaw

    try:
        caselaw = CaseLaw.objects.get(pk=caselaw_id)
    except CaseLaw.DoesNotExist:
        return

    try:
        opinion_text = ""
        if caselaw.opinion_id:
            opinion = fetch_opinion(caselaw.opinion_id)
            if opinion.found:
                opinion_text = opinion.plain_text
        elif caselaw.cluster_id:
            opinion_text = _get_opinion_text(caselaw.cluster_id)

        if not opinion_text:
            return

        truncated = opinion_text[:15000]

        system_prompt = (
            "You are a legal research assistant. Write clear, concise prose."
        )
        user_prompt = (
            f"Write a 200-word summary of this case. Focus on the key facts, "
            f"the legal issue, and the court's holding.\n\n"
            f"Case: {caselaw.case_name}\n"
            f"Citation: {caselaw.citation}\n"
            f"Court: {caselaw.court}\n"
            f"Date: {caselaw.date_filed}\n\n"
            f"Opinion Text:\n{truncated}"
        )

        response_text, _, _ = send_to_gemini(
            system_prompt, [{"role": "user", "content": user_prompt}]
        )

        CaseLaw.objects.filter(pk=caselaw_id).update(summary=response_text.strip())

    except Exception:
        logger.exception("Error generating summary for case law %s", caselaw_id)


def generate_brief(brief_id):
    """Run case brief generation in a background daemon thread."""
    thread = threading.Thread(target=_generate_brief, args=(brief_id,), daemon=True)
    thread.start()


def _get_opinion_text(cluster_id):
    """Fetch opinion plain text from CourtListener given a cluster_id."""
    cluster = fetch_cluster(cluster_id)
    if not cluster:
        return ""

    sub_opinions = cluster.get("sub_opinions", [])
    if not sub_opinions:
        return ""

    try:
        opinion_id = int(sub_opinions[0].rstrip("/").split("/")[-1])
    except (ValueError, IndexError):
        return ""

    opinion = fetch_opinion(opinion_id)
    return opinion.plain_text if opinion.found else ""


def _generate_brief(brief_id):
    """Generate an AI case brief from the opinion text."""
    try:
        brief = CaseBrief.objects.get(pk=brief_id)
    except CaseBrief.DoesNotExist:
        return

    CaseBrief.objects.filter(pk=brief_id).update(status="generating")

    try:
        # Get opinion text — try the linked result first, otherwise fetch fresh
        opinion_text = ""
        if brief.result and brief.result.opinion_text:
            opinion_text = brief.result.opinion_text
        elif brief.cluster_id:
            opinion_text = _get_opinion_text(brief.cluster_id)

        if not opinion_text:
            CaseBrief.objects.filter(pk=brief_id).update(
                status="error", brief="Could not retrieve opinion text."
            )
            return

        truncated = opinion_text[:15000]

        system_prompt = "You are a legal research assistant. Write clear, well-structured case briefs."

        research_context = ""
        if brief.query_text:
            research_context = (
                f"The user is researching: {brief.query_text}\n"
                f"Focus the brief on the aspects of this case that are relevant to "
                f"that research question. Frame the issue, holding, and reasoning "
                f"in terms of how they relate to the research question.\n\n"
            )

        user_prompt = (
            f"Write a law school-style case brief for the following case. "
            f"Use exactly these four markdown headings: ## Facts, ## Issue, ## Holding, ## Reasoning\n\n"
            f"{research_context}"
            f"Keep each section concise and focused.\n\n"
            f"Case: {brief.case_name}\n"
            f"Citation: {brief.citation}\n"
            f"Court: {brief.court}\n"
            f"Date: {brief.date_filed}\n\n"
            f"Opinion Text:\n{truncated}"
        )

        response_text, _, _ = send_to_gemini(
            system_prompt, [{"role": "user", "content": user_prompt}]
        )

        CaseBrief.objects.filter(pk=brief_id).update(
            brief=response_text.strip(), status="complete"
        )

    except Exception:
        logger.exception("Error generating case brief %s", brief_id)
        CaseBrief.objects.filter(pk=brief_id).update(status="error")
