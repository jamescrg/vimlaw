"""Background task for processing research queries."""

import json
import logging
import re
import threading

import requests

from apps.case.ai.gemini_client import send_to_gemini
from apps.case.courtlistener import (
    API_V4_URL,
    fetch_cluster,
    fetch_opinion,
    get_api_token,
)

from .courtlistener import (
    count_forward_citations,
    get_forward_citations,
    search_opinions,
)
from .jurisdictions import get_court_ids
from .models import CaseBrief, CitationVerification, ResearchQuery, ResearchResult

logger = logging.getLogger(__name__)


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
        "CourtListener search syntax (Solr-based):\n"
        "- AND (or &): intersection (AND is the default between terms)\n"
        "- OR: union of alternatives\n"
        "- NOT (or - prefix): exclude terms\n"
        '- "quoted phrase": exact phrase match, no stemming\n'
        "- (parentheses): group expressions, may be nested\n"
        '- "phrase"~N: proximity — words within N words of each other (ONLY after quoted phrases)\n'
        "- term~: fuzzy match for spelling variations (no number after ~)\n"
        "- stem*: wildcard prefix matching — matches all words starting with the stem\n"
        "  Examples: waiv* → waive, waived, waiver; negligen* → negligence, negligent, negligently\n"
        "  Use wildcards instead of OR-listing inflections of the same word:\n"
        "  BAD:  (waive OR waived OR waiver OR waiving)\n"
        "  GOOD: waiv*\n"
        "  OR groups are still correct for genuinely different terms (e.g. suit OR action)\n"
        '- "phrase"~N: proximity — words within N words of each other (ONLY after quoted phrases)\n'
        "- term~: fuzzy match for spelling variations (no number after ~)\n\n"
        "CRITICAL SYNTAX RULES — violating these causes server errors:\n"
        "- The ~ operator ONLY works two ways:\n"
        '  1. "quoted phrase"~N → proximity (OK: "summary judgment"~5)\n'
        "  2. word~ → fuzzy spelling (OK: negligen~)\n"
        "- NEVER write word~N (e.g. motion~3) — this is INVALID and will crash the search\n"
        "- NEVER use ~ between or after bare words for proximity — use quoted phrases instead\n"
        "- Parentheses MUST be balanced\n"
        "- Quotes MUST be balanced\n"
        "- Do NOT use fielded search (e.g. court_id:) — court filtering is handled separately\n"
        "- Do NOT use range queries [x TO y] — not supported on the full-text search field\n\n"
        "Guidelines:\n"
        "- Use stem* wildcards for word inflections instead of OR-listing every form\n"
        '- Use OR groups for genuinely different terms or phrases (e.g. suit OR action OR "cause of action")\n'
        "- Use proximity operators on quoted phrases for multi-word concepts\n"
        "- Group related concepts with parentheses and connect groups with AND\n"
        "- Keep the query under 3 levels of nesting to avoid complexity issues\n"
        "- Keep the query concise — 120 characters or fewer\n\n"
        "Example input: Can a joint tenant with right of survivorship file an "
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
    """Process a research query: search, evaluate, summarize (refinement already done)."""
    try:
        query = ResearchQuery.objects.get(pk=query_id)
    except ResearchQuery.DoesNotExist:
        return

    try:
        # Phase 1: Search CourtListener
        ResearchQuery.objects.filter(pk=query_id).update(status="searching")

        search_text = query.structured_query or query.query_text
        court = get_court_ids(query.state, query.include_federal)

        results, status_code = search_opinions(search_text, court=court, limit=10)

        # If the structured query caused a server error, retry with raw query text
        if not results and status_code == 500 and query.structured_query:
            logger.warning(
                "Structured query failed for %s, retrying with raw text", query_id
            )
            results, status_code = search_opinions(
                query.query_text, court=court, limit=10
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

        # Deduplicate by cluster_id and by citation + date_filed
        seen_clusters = set()
        seen_citations = set()
        unique_results = []
        for result in results:
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
            unique_results.append(result)
        results = unique_results

        # Create result records
        for i, result in enumerate(results, 1):
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
                courtlistener_url=result.get("courtlistener_url", ""),
            )

        ResearchQuery.objects.filter(pk=query_id).update(status="processing")

        # Phase 2: Process each result (in CL relevance order)
        result_records = ResearchResult.objects.filter(query_id=query_id).order_by(
            "position"
        )

        for result in result_records:
            try:
                _process_result(result, query.query_text)
            except Exception:
                logger.exception("Error processing result %s", result.id)
                ResearchResult.objects.filter(pk=result.id).update(
                    relevance="error", status_message="Error during processing"
                )

        # Phase 2.5: Reorder by assessed relevance — high first, medium after, low removed
        ResearchResult.objects.filter(query_id=query_id, relevance="low").delete()

        RELEVANCE_ORDER = {"high": 0, "medium": 1, "error": 2}
        remaining = list(
            ResearchResult.objects.filter(query_id=query_id).order_by("position")
        )
        remaining.sort(key=lambda r: (RELEVANCE_ORDER.get(r.relevance, 1), r.position))
        for i, result in enumerate(remaining, 1):
            if result.position != i:
                ResearchResult.objects.filter(pk=result.id).update(position=i)

        # Phase 3: Final summary
        _generate_final_summary(query_id)

    except Exception:
        logger.exception("Error processing research query %s", query_id)
        ResearchQuery.objects.filter(pk=query_id).update(
            status="error", error_message="An unexpected error occurred."
        )


def _process_result(result, query_text):
    """Download opinion and evaluate relevance for a single result."""
    result_id = result.id

    if not result.cluster_id:
        ResearchResult.objects.filter(pk=result_id).update(
            relevance="error", status_message="No cluster ID"
        )
        return

    # Download opinion
    ResearchResult.objects.filter(pk=result_id).update(
        status_message="Downloading opinion..."
    )

    cluster = fetch_cluster(result.cluster_id)
    if not cluster:
        ResearchResult.objects.filter(pk=result_id).update(
            relevance="error", status_message="Could not fetch case details"
        )
        return

    # Get opinion ID from cluster
    sub_opinions = cluster.get("sub_opinions", [])
    if not sub_opinions:
        ResearchResult.objects.filter(pk=result_id).update(
            relevance="error", status_message="No opinion text available"
        )
        return

    opinion_url = sub_opinions[0]
    try:
        opinion_id = int(opinion_url.rstrip("/").split("/")[-1])
    except (ValueError, IndexError):
        ResearchResult.objects.filter(pk=result_id).update(
            relevance="error", status_message="Could not parse opinion ID"
        )
        return

    # Fetch forward citation count
    fwd_count = count_forward_citations(opinion_id)
    if fwd_count is not None:
        ResearchResult.objects.filter(pk=result_id).update(
            forward_citation_count=fwd_count
        )

    opinion = fetch_opinion(opinion_id)
    if not opinion.found:
        ResearchResult.objects.filter(pk=result_id).update(
            relevance="error", status_message="Could not fetch opinion text"
        )
        return

    # Store opinion text temporarily
    ResearchResult.objects.filter(pk=result_id).update(
        opinion_text=opinion.plain_text[:50000]
    )

    # Evaluate relevance with Gemini
    ResearchResult.objects.filter(pk=result_id).update(
        status_message="Evaluating relevance..."
    )

    truncated_text = opinion.plain_text[:8000]
    system_prompt = "You are a legal research assistant. Respond ONLY with valid JSON."
    user_prompt = f"""Evaluate the relevance of this case to the following legal research query.

Research Query: {query_text}

Case: {result.case_name}
Court: {result.court}
Date Filed: {result.date_filed}

Opinion Text (excerpt):
{truncated_text}

Respond with JSON in this exact format:
{{"relevance": "high" or "medium" or "low", "reason": "brief explanation", """
    user_prompt += """"summary": "100-word summary if relevance is high, otherwise empty string"}}"""

    try:
        response_text, _, _ = send_to_gemini(
            system_prompt, [{"role": "user", "content": user_prompt}]
        )

        # Parse JSON from response (handle markdown code blocks)
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        parsed = json.loads(cleaned)
        relevance = parsed.get("relevance", "medium")
        if relevance not in ("high", "medium", "low"):
            relevance = "medium"

        summary = parsed.get("summary", "") if relevance == "high" else ""

        ResearchResult.objects.filter(pk=result_id).update(
            relevance=relevance,
            gemini_summary=summary,
            status_message="Complete",
        )

    except (json.JSONDecodeError, KeyError):
        logger.exception("Failed to parse Gemini response for result %s", result_id)
        ResearchResult.objects.filter(pk=result_id).update(
            relevance="medium", status_message="Complete"
        )
    except Exception:
        logger.exception("Gemini error for result %s", result_id)
        ResearchResult.objects.filter(pk=result_id).update(
            relevance="error", status_message="AI evaluation failed"
        )


def _generate_final_summary(query_id):
    """Generate a synthesis of all high-relevance results."""
    query = ResearchQuery.objects.get(pk=query_id)
    high_results = ResearchResult.objects.filter(
        query_id=query_id, relevance="high"
    ).exclude(gemini_summary="")

    if not high_results.exists():
        ResearchQuery.objects.filter(pk=query_id).update(status="complete")
        return

    summaries = []
    for r in high_results:
        summaries.append(f"- {r.case_name}: {r.gemini_summary}")

    summaries_text = "\n".join(summaries)

    system_prompt = "You are a legal research assistant synthesizing case law findings."
    user_prompt = f"""Based on the following legal research query and relevant case summaries, \
provide a 200-word synthesis of the key legal principles and how these cases address the query.

Research Query: {query.query_text}

Relevant Cases:
{summaries_text}

Provide a concise synthesis:"""

    try:
        response_text, _, _ = send_to_gemini(
            system_prompt, [{"role": "user", "content": user_prompt}]
        )

        ResearchQuery.objects.filter(pk=query_id).update(
            status="complete", final_summary=response_text.strip()
        )

    except Exception:
        logger.exception("Error generating final summary for query %s", query_id)
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

        response = requests.get(
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
