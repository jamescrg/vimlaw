"""Background task for processing research queries."""

import json
import logging
import threading

from apps.case.ai.gemini_client import send_to_gemini
from apps.case.courtlistener import fetch_cluster, fetch_opinion

from .courtlistener import search_opinions
from .jurisdictions import get_court_ids
from .models import ResearchQuery, ResearchResult

logger = logging.getLogger(__name__)


def process_research_query(query_id):
    """Run research query processing in a background daemon thread."""
    thread = threading.Thread(target=_process_query, args=(query_id,), daemon=True)
    thread.start()


def _refine_query(query_id):
    """Use AI to convert natural language query into structured search syntax."""
    ResearchQuery.objects.filter(pk=query_id).update(status="refining")

    query = ResearchQuery.objects.get(pk=query_id)

    system_prompt = (
        "You are a legal search query optimizer. Convert the user's natural language "
        "legal research question into an optimized search query for CourtListener. "
        "Use search syntax: AND, OR, NOT, quoted phrases for exact match, parenthetical "
        'grouping, proximity operator ~N (e.g. "negligence duty"~5), and wildcards *. '
        "Return ONLY the search query string, nothing else."
    )
    user_prompt = f"Convert this legal research question into an optimized search query:\n\n{query.query_text}"

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


def _process_query(query_id):
    """Process a research query: refine, search, evaluate, summarize."""
    try:
        query = ResearchQuery.objects.get(pk=query_id)
    except ResearchQuery.DoesNotExist:
        return

    try:
        # Phase 0: Refine query with AI
        _refine_query(query_id)

        # Reload to get structured_query
        query = ResearchQuery.objects.get(pk=query_id)

        # Phase 1: Search CourtListener
        ResearchQuery.objects.filter(pk=query_id).update(status="searching")

        search_text = query.structured_query or query.query_text
        court = get_court_ids(query.state, query.include_federal)

        results = search_opinions(search_text, court=court, limit=5)

        if not results:
            ResearchQuery.objects.filter(pk=query_id).update(
                status="error", error_message="No results found on CourtListener."
            )
            return

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
