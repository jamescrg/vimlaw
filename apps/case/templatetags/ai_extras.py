"""Template filters for the AI chat's agent trail and status strip.

Formatting lives here rather than in the views so the live status box and
the persisted trail render the same numbers the same way.
"""

from django import template

register = template.Library()

TOOL_ICONS = {
    "search_materials": "icon-file-search",
    "read_document": "icon-file-text",
    "read_email_thread": "icon-mail",
    "read_note": "icon-scroll-text",
    "read_caselaw": "icon-scale",
    "read_conversation": "icon-message-circle",
    "read_invoice": "icon-receipt",
    "read_matter_section": "icon-book-open",
}


def _number(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


@register.filter
def ktokens(value):
    """48231 -> 48.2k, 812 -> 812, 1200000 -> 1.2M."""
    n = _number(value)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


@register.filter
def kchars(value):
    return ktokens(value)


@register.filter
def duration_short(value):
    """72 -> 1m 12s, 9 -> 9s, 3725 -> 1h 2m."""
    total = _number(value)
    if total >= 3600:
        hours, rest = divmod(total, 3600)
        return f"{hours}h {rest // 60}m"
    if total >= 60:
        minutes, seconds = divmod(total, 60)
        return f"{minutes}m {seconds}s"
    return f"{total}s"


@register.filter
def agent_tool_icon(name):
    return TOOL_ICONS.get(name or "", "icon-wrench")
