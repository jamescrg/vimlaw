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


@register.filter
def turn_summary(step):
    """One line for a turn divider: 12.3k in, 610 out, 11.9k cached, 9s."""
    step = step or {}
    parts = [f"{ktokens(step.get('input'))} in", f"{ktokens(step.get('output'))} out"]
    if step.get("cache_read"):
        parts.append(f"{ktokens(step['cache_read'])} cached")
    if step.get("seconds"):
        parts.append(duration_short(step["seconds"]))
    return ", ".join(parts)


@register.filter
def usd(value):
    """$0.55 style; sub-cent amounts show as <$0.01; None renders empty."""
    if value is None:
        return ""
    value = float(value)
    if 0 < value < 0.01:
        return "<$0.01"
    return f"${value:,.2f}"


@register.simple_tag
def usage_cost(usage, llm):
    """Estimated cost of a live run's usage so far, formatted, or ""."""
    from apps.case.ai.pricing import estimate_cost

    usage = usage or {}
    cost = estimate_cost(
        llm,
        usage.get("input"),
        usage.get("output"),
        usage.get("cache_read"),
        usage.get("cache_write"),
    )
    return usd(cost) if cost is not None else ""
