"""CourtListener search API wrapper for legal research."""

import logging

import requests

from apps.case.courtlistener import API_V4_URL, get_api_token

logger = logging.getLogger(__name__)

COURTLISTENER_BASE_URL = "https://www.courtlistener.com"


def get_forward_citations(opinion_id, limit=5):
    """
    Fetch forward citations for an opinion, sorted by citation depth (descending).

    Returns list of dicts with citing_opinion_id and depth.
    """
    api_token = get_api_token()
    if not api_token:
        return []

    try:
        response = requests.get(
            f"{API_V4_URL}/opinions-cited/",
            headers={"Authorization": f"Token {api_token}"},
            params={
                "cited_opinion": opinion_id,
                "order_by": "-depth",
                "page_size": limit,
            },
            timeout=30,
        )

        if response.status_code != 200:
            logger.error(
                "Forward citations fetch failed: %s - %s",
                response.status_code,
                response.text[:200],
            )
            return []

        data = response.json()
        results = []
        for item in data.get("results", [])[:limit]:
            citing_url = item.get("citing_opinion", "")
            try:
                citing_id = int(citing_url.rstrip("/").split("/")[-1])
            except (ValueError, IndexError):
                continue
            results.append(
                {
                    "citing_opinion_id": citing_id,
                    "depth": item.get("depth", 0),
                }
            )
        return results

    except requests.RequestException as e:
        logger.exception("Error fetching forward citations: %s", e)
        return []


def count_forward_citations(opinion_id):
    """Get the total number of forward citations for an opinion."""
    api_token = get_api_token()
    if not api_token:
        return None

    try:
        response = requests.get(
            f"{API_V4_URL}/opinions-cited/",
            headers={"Authorization": f"Token {api_token}"},
            params={
                "cited_opinion": opinion_id,
                "count": "on",
            },
            timeout=30,
        )

        if response.status_code != 200:
            return None

        return response.json().get("count", 0)

    except requests.RequestException:
        return None


def search_opinions(query, court="", limit=5):
    """
    Search CourtListener for opinions matching a query.

    Args:
        query: Natural language search query
        court: CourtListener court ID to filter by (empty for all)
        limit: Number of results to return

    Returns:
        List of result dicts with case_name, court, date_filed, etc.
    """
    api_token = get_api_token()
    if not api_token:
        return []

    params = {
        "q": query,
        "type": "o",
        "page_size": limit,
    }
    if court:
        params["court"] = court

    try:
        response = requests.get(
            f"{API_V4_URL}/search/",
            headers={"Authorization": f"Token {api_token}"},
            params=params,
            timeout=30,
        )

        if response.status_code != 200:
            logger.error(
                "CourtListener search failed: %s - %s",
                response.status_code,
                response.text[:200],
            )
            return []

        data = response.json()
        results = []

        for item in data.get("results", [])[:limit]:
            cluster_id = item.get("cluster_id")
            results.append(
                {
                    "case_name": item.get("caseName", ""),
                    "citation": item.get("citation", []),
                    "court": item.get("court", ""),
                    "date_filed": item.get("dateFiled", ""),
                    "cluster_id": cluster_id,
                    "snippet": item.get("snippet", ""),
                    "score": item.get("score"),
                    "courtlistener_url": (
                        f"{COURTLISTENER_BASE_URL}{item['absolute_url']}"
                        if item.get("absolute_url")
                        else ""
                    ),
                }
            )

        return results

    except requests.RequestException as e:
        logger.exception("Error searching CourtListener: %s", e)
        return []
