"""
CourtListener API client for fetching case law.

Provides functions to look up citations and retrieve full opinion text.
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

COURTLISTENER_BASE_URL = "https://www.courtlistener.com"
API_V4_URL = f"{COURTLISTENER_BASE_URL}/api/rest/v4"


@dataclass
class CaseLookupResult:
    """Result from looking up a citation."""

    found: bool
    case_name: str = ""
    citation: str = ""
    court: str = ""
    court_id: str = ""
    date_filed: Optional[date] = None
    docket_number: str = ""
    cluster_id: Optional[int] = None
    absolute_url: str = ""
    error: str = ""


@dataclass
class OpinionResult:
    """Result from fetching an opinion."""

    found: bool
    opinion_id: Optional[int] = None
    plain_text: str = ""
    html_with_citations: str = ""
    author: str = ""
    error: str = ""


def get_api_token() -> str:
    """Get CourtListener API token from settings."""
    return getattr(settings, "COURTLISTENER_API_TOKEN", "")


def lookup_citation(citation_text: str) -> CaseLookupResult:
    """
    Look up a citation using CourtListener's citation-lookup API.

    Args:
        citation_text: The citation to look up (e.g., "410 U.S. 113")

    Returns:
        CaseLookupResult with case info if found
    """
    api_token = get_api_token()
    if not api_token:
        return CaseLookupResult(found=False, error="No API token configured")

    try:
        response = requests.post(
            f"{API_V4_URL}/citation-lookup/",
            headers={"Authorization": f"Token {api_token}"},
            data={"text": citation_text},
            timeout=30,
        )

        if response.status_code != 200:
            logger.error(
                "Citation lookup failed: %s - %s",
                response.status_code,
                response.text[:200],
            )
            return CaseLookupResult(
                found=False, error=f"API error: {response.status_code}"
            )

        results = response.json()
        if not results:
            return CaseLookupResult(found=False, error="No results found")

        # Get the first result with status 200 (found)
        for result in results:
            if result.get("status") == 200 and result.get("clusters"):
                cluster = result["clusters"][0]

                # Parse date if present
                date_filed = None
                if cluster.get("date_filed"):
                    try:
                        date_filed = date.fromisoformat(cluster["date_filed"])
                    except (ValueError, TypeError):
                        pass

                return CaseLookupResult(
                    found=True,
                    case_name=cluster.get("case_name", ""),
                    citation=result.get("citation", citation_text),
                    court=cluster.get("court", ""),
                    court_id=cluster.get("court_id", ""),
                    date_filed=date_filed,
                    docket_number=cluster.get("docket_number", ""),
                    cluster_id=cluster.get("id"),
                    absolute_url=cluster.get("absolute_url", ""),
                )

        return CaseLookupResult(found=False, error="Citation not found in database")

    except requests.RequestException as e:
        logger.exception("Error looking up citation: %s", e)
        return CaseLookupResult(found=False, error=f"Request failed: {str(e)}")


def fetch_cluster(cluster_id: int) -> dict:
    """
    Fetch cluster (case) metadata from CourtListener.

    Args:
        cluster_id: The CourtListener cluster ID

    Returns:
        Dict with cluster data or empty dict on error
    """
    api_token = get_api_token()
    if not api_token:
        return {}

    try:
        response = requests.get(
            f"{API_V4_URL}/clusters/{cluster_id}/",
            headers={"Authorization": f"Token {api_token}"},
            timeout=30,
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(
                "Cluster fetch failed: %s - %s",
                response.status_code,
                response.text[:200],
            )
            return {}

    except requests.RequestException as e:
        logger.exception("Error fetching cluster %s: %s", cluster_id, e)
        return {}


def fetch_opinion(opinion_id: int) -> OpinionResult:
    """
    Fetch full opinion text from CourtListener.

    Args:
        opinion_id: The CourtListener opinion ID

    Returns:
        OpinionResult with opinion text
    """
    api_token = get_api_token()
    if not api_token:
        return OpinionResult(found=False, error="No API token configured")

    try:
        response = requests.get(
            f"{API_V4_URL}/opinions/{opinion_id}/",
            headers={"Authorization": f"Token {api_token}"},
            timeout=60,  # Opinions can be large
        )

        if response.status_code != 200:
            logger.error(
                "Opinion fetch failed: %s - %s",
                response.status_code,
                response.text[:200],
            )
            return OpinionResult(
                found=False, error=f"API error: {response.status_code}"
            )

        data = response.json()

        # Get best available text
        plain_text = (
            data.get("plain_text")
            or data.get("html_with_citations")
            or data.get("html")
            or ""
        )

        # Strip HTML if we got HTML instead of plain text
        if plain_text.startswith("<"):
            # Basic HTML stripping - the html_with_citations is the richest
            import re

            plain_text = re.sub(r"<[^>]+>", "", plain_text)

        return OpinionResult(
            found=True,
            opinion_id=data.get("id"),
            plain_text=plain_text,
            html_with_citations=data.get("html_with_citations", ""),
            author=data.get("author_str", ""),
        )

    except requests.RequestException as e:
        logger.exception("Error fetching opinion %s: %s", opinion_id, e)
        return OpinionResult(found=False, error=f"Request failed: {str(e)}")


def format_citations_with_year(citations: list, date_filed: Optional[date]) -> str:
    """
    Format citations list into a string with parallel citations and year.

    Args:
        citations: List of citation dicts from CourtListener
                   Each has 'volume', 'reporter', 'page' fields
        date_filed: The date the case was filed (for the year)

    Returns:
        Formatted citation string like "279 Ga. 326, 613 S.E.2d 159 (2005)"
    """
    if not citations:
        return ""

    # Sort by type (lower type = state reporter, should come first)
    sorted_citations = sorted(citations, key=lambda c: c.get("type", 99))

    # Build citation strings from volume/reporter/page
    cite_strings = []
    for c in sorted_citations:
        volume = c.get("volume", "")
        reporter = c.get("reporter", "")
        page = c.get("page", "")
        if volume and reporter and page:
            cite_strings.append(f"{volume} {reporter} {page}")

    if not cite_strings:
        return ""

    # Join with ", " for parallel citations
    combined = ", ".join(cite_strings)

    # Add year if available
    if date_filed:
        combined = f"{combined} ({date_filed.year})"

    return combined


def fetch_case_by_citation(citation_text: str) -> dict:
    """
    Convenience function to look up a citation and fetch the full case.

    Args:
        citation_text: The citation to look up

    Returns:
        Dict with full case data or error info:
        {
            "found": bool,
            "case_name": str,
            "citation": str,
            "court": str,
            "court_id": str,
            "date_filed": date or None,
            "docket_number": str,
            "cluster_id": int,
            "opinion_id": int,
            "courtlistener_url": str,
            "text": str,
            "html": str,
            "error": str,
        }
    """
    # Step 1: Look up the citation
    lookup = lookup_citation(citation_text)
    if not lookup.found:
        return {"found": False, "error": lookup.error}

    # Step 2: Fetch cluster to get opinion IDs and full citation info
    cluster = fetch_cluster(lookup.cluster_id)
    if not cluster:
        return {"found": False, "error": "Could not fetch case details"}

    # Get the first (main) opinion ID from sub_opinions
    sub_opinions = cluster.get("sub_opinions", [])
    if not sub_opinions:
        return {"found": False, "error": "No opinion text available"}

    # sub_opinions contains URLs like "/api/rest/v4/opinions/123/"
    # Extract the ID from the first one
    opinion_url = sub_opinions[0]
    try:
        opinion_id = int(opinion_url.rstrip("/").split("/")[-1])
    except (ValueError, IndexError):
        return {"found": False, "error": "Could not parse opinion ID"}

    # Step 3: Fetch the opinion text
    opinion = fetch_opinion(opinion_id)
    if not opinion.found:
        return {"found": False, "error": opinion.error}

    # Convert date to string for JSON serialization (session storage)
    date_filed_str = lookup.date_filed.isoformat() if lookup.date_filed else None

    # Get all citations from cluster (includes parallel citations)
    citations = cluster.get("citations", [])
    full_citation = format_citations_with_year(citations, lookup.date_filed)

    # Fall back to the lookup citation if cluster didn't have citations
    if not full_citation:
        full_citation = lookup.citation
        if lookup.date_filed:
            full_citation = f"{full_citation} ({lookup.date_filed.year})"

    return {
        "found": True,
        "case_name": lookup.case_name,
        "citation": full_citation,
        "court": lookup.court,
        "court_id": lookup.court_id,
        "date_filed": date_filed_str,
        "docket_number": lookup.docket_number,
        "cluster_id": lookup.cluster_id,
        "opinion_id": opinion.opinion_id,
        "courtlistener_url": f"{COURTLISTENER_BASE_URL}{lookup.absolute_url}",
        "text": opinion.plain_text,
        "html": opinion.html_with_citations,
        "error": "",
    }
