"""Process-wide throttle for CourtListener API calls.

Every CourtListener request in the app (citation lookups, cluster/opinion
fetches, searches, forward-citation queries) funnels through
``throttled_request`` so concurrent callers — the vetting thread pool, the
research pipeline, and the research chat's tool loop — share one polite
request rate instead of stampeding the API. Since CourtListener's May
2026 policy change, limits are per-account membership tiers (ours: Free
Law Project Tier 3, 20/minute, 250/hour, 1,000/day), so the spacing is
deliberately conservative and the 429 backoff carries the rest.

Behavior: enforce a minimum interval between requests (spacing bookkeeping
under a lock, the HTTP call itself outside it); on 429 honor Retry-After
(capped) or exponentially back off and retry; on 5xx retry once; never
retry other 4xx. Callers keep handling non-200s exactly as before — this
module only adds spacing and retries, never changes shapes.
"""

import logging
import random
import threading
import time

import requests

logger = logging.getLogger(__name__)

_MIN_INTERVAL = 0.25  # seconds between requests, process-wide
_MAX_BACKOFF = 30.0

_lock = threading.Lock()
_next_slot = 0.0


def _wait_for_slot():
    """Sleep until this thread's reserved request slot arrives."""
    global _next_slot
    with _lock:
        now = time.monotonic()
        slot = max(now, _next_slot)
        _next_slot = slot + _MIN_INTERVAL
    delay = slot - now
    if delay > 0:
        time.sleep(delay)


def throttled_request(method, url, *, max_retries=3, **kwargs):
    """A rate-limited ``requests.request`` with 429/5xx retry.

    Returns the final Response (which may still be a 429/5xx after retries
    are exhausted — callers already handle non-200s).
    """
    response = None
    for attempt in range(max_retries + 1):
        _wait_for_slot()
        response = requests.request(method, url, **kwargs)

        if response.status_code == 429:
            if attempt >= max_retries:
                break
            retry_after = response.headers.get("Retry-After")
            try:
                delay = min(float(retry_after), _MAX_BACKOFF)
            except (TypeError, ValueError):
                delay = min(2.0**attempt + random.uniform(0, 1), _MAX_BACKOFF)
            logger.warning(
                "CourtListener 429; backing off %.1fs (attempt %s)", delay, attempt + 1
            )
            time.sleep(delay)
            continue

        if 500 <= response.status_code < 600 and attempt == 0:
            logger.warning(
                "CourtListener %s on %s; one retry", response.status_code, url
            )
            time.sleep(1.0 + random.uniform(0, 1))
            continue

        break

    return response
