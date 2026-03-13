"""Background task for processing research queries."""

import json
import logging
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
from .models import CitationVerification, ResearchQuery, ResearchResult

logger = logging.getLogger(__name__)


def refine_research_query(query_id):
    """Run query refinement in a background daemon thread, then pause for user review."""
    thread = threading.Thread(target=_refine_and_pause, args=(query_id,), daemon=True)
    thread.start()


def process_research_query(query_id):
    """Run search + processing in a background daemon thread (after user confirms)."""
    thread = threading.Thread(target=_process_query, args=(query_id,), daemon=True)
    thread.start()


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
        "CourtListener search syntax:\n"
        "- AND (or &): intersection (AND is the default between terms)\n"
        "- OR: union of alternatives\n"
        "- NOT (or - prefix): exclude terms\n"
        '- "quoted phrase": exact phrase match, no stemming\n'
        "- (parentheses): group expressions, may be nested\n"
        '- "phrase"~N: proximity — words within N words of each other\n'
        "- term~: fuzzy match for spelling variations (e.g. negligen~)\n"
        "- wild*: wildcard matching (* for multiple chars, ? for single)\n"
        "- [x TO y]: range queries (numbers or dates)\n\n"
        "Important: the ~ operator means different things depending on context:\n"
        '- After a quoted phrase ("border fence"~50) it is a proximity operator\n'
        "- After a single word (immigrant~) it is a fuzzy/spelling operator\n"
        "Do NOT use ~N after a single word for proximity.\n\n"
        "Guidelines:\n"
        "- Use OR groups for synonyms and alternative legal phrasings\n"
        "- Use proximity operators for multi-word concepts that may appear in varied forms\n"
        "- Group related concepts with parentheses and connect groups with AND\n"
        "- Be expansive with alternatives — more OR branches improve recall\n"
        "- Do NOT use fielded search (e.g. court_id:) — court filtering is handled separately\n\n"
        "Example input: Can a joint tenant with right of survivorship file an "
        "equitable partition suit?\n"
        'Example output: (("joint tenant"~5 "right of survivorship") OR '
        '"joint tenancy with right of survivorship") AND ("equitable partition" '
        'OR partition) AND (suit OR "file suit" OR action OR "legal action")\n\n'
        "Return ONLY the search query string, nothing else."
    )
    user_prompt = query.query_text

    try:
        response_text, _, _ = send_to_gemini(
            system_prompt, [{"role": "user", "content": user_prompt}]
        )
        structured = response_text.strip().strip("`").strip()
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

        results = search_opinions(search_text, court=court, limit=10)

        if not results:
            ResearchQuery.objects.filter(pk=query_id).update(
                status="error", error_message="No results found on CourtListener."
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

        # Phase 2: Process each result
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


def verify_result(result_id):
    """Run citation verification in a background daemon thread."""
    thread = threading.Thread(target=_verify_result, args=(result_id,), daemon=True)
    thread.start()


def _verify_result(result_id):
    """Fetch top forward citations by depth and summarize their treatment."""
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

        # Fetch top 5 forward citations by depth
        forward_cites = get_forward_citations(opinion_id, limit=5)
        if not forward_cites:
            ResearchResult.objects.filter(pk=result_id).update(verify_status="complete")
            return

        query_text = result.query.query_text

        for i, cite in enumerate(forward_cites, 1):
            citing_id = cite["citing_opinion_id"]
            depth = cite["depth"]

            # Fetch the citing opinion
            citing_opinion = fetch_opinion(citing_id)
            if not citing_opinion.found:
                continue

            # Get cluster info for the citing opinion's metadata
            # The opinion endpoint gives us the cluster URL
            citing_meta = _get_opinion_metadata(citing_id)

            # Summarize the citing opinion's treatment
            truncated = citing_opinion.plain_text[:8000]
            system_prompt = (
                "You are a legal research assistant. Respond ONLY with valid JSON."
            )
            user_prompt = (
                f"This opinion cites {result.case_name}. Analyze how this citing opinion "
                f"treats the cited case and its relevance to the research query.\n\n"
                f"Research Query: {query_text}\n"
                f"Original Case: {result.case_name} ({result.citation})\n\n"
                f"Citing Opinion Text (excerpt):\n{truncated}\n\n"
                f'Respond with JSON: {{"treatment": "positive/negative/neutral/distinguished",'
                f' "summary": "2-3 sentence summary of how this opinion treats the cited case '
                f'and its relevance to the research query"}}'
            )

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
                detail = parsed.get("summary", "")
                summary = f"**{treatment.title()}** — {detail}" if detail else treatment
            except Exception:
                logger.exception("Error summarizing forward citation %s", citing_id)
                summary = "Could not analyze treatment."

            CitationVerification.objects.create(
                result_id=result_id,
                position=i,
                case_name=citing_meta.get("case_name", ""),
                citation=citing_meta.get("citation", ""),
                court=citing_meta.get("court", ""),
                date_filed=citing_meta.get("date_filed", ""),
                cluster_id=citing_meta.get("cluster_id"),
                courtlistener_url=citing_meta.get("courtlistener_url", ""),
                depth=depth,
                summary=summary,
            )

        ResearchResult.objects.filter(pk=result_id).update(verify_status="complete")

    except Exception:
        logger.exception("Error verifying result %s", result_id)
        ResearchResult.objects.filter(pk=result_id).update(verify_status="error")


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
