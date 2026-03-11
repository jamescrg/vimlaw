"""CourtListener search API wrapper for legal research."""

import logging

import requests

from apps.case.courtlistener import API_V4_URL, get_api_token

logger = logging.getLogger(__name__)

COURTLISTENER_BASE_URL = "https://www.courtlistener.com"


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
                        f"{COURTLISTENER_BASE_URL}/opinion/{cluster_id}/"
                        if cluster_id
                        else ""
                    ),
                }
            )

        return results

    except requests.RequestException as e:
        logger.exception("Error searching CourtListener: %s", e)
        return []
