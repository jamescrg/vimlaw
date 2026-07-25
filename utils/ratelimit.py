"""Best-effort IP rate limiting for public (no-login) endpoints.

Public surfaces have no session to throttle against, so the client IP is all we
have. This is deliberately cheap and approximate: a fixed window in the Django
cache, no sliding average, no lockout. It exists to blunt scripted abuse of the
tokenized pages, not to be an authorization control — the signed token is what
actually gates access.

Caveat worth knowing before you tune the numbers: `config/settings.py` declares
no CACHES block, so Django falls back to a per-process LocMemCache. Limits are
therefore per gunicorn worker (an N-worker deploy effectively allows N× the
stated limit) and reset on restart. A shared cache backend would fix that
globally for every caller here.
"""

from django.core.cache import cache


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def rate_limited(request, scope, *, limit, window):
    """True once this IP has exceeded `limit` requests to `scope` in `window`
    seconds. Callers translate that into a 429."""
    key = f"ratelimit:{scope}:{client_ip(request)}"
    try:
        cache.get_or_set(key, 0, window)
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, window)
        count = 1
    return count > limit
