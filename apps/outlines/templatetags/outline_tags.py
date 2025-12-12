"""Template tags and filters for the outlines app."""

import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def inline_markdown(text):
    """
    Convert limited markdown syntax to HTML.

    Supports:
    - **bold** or __bold__ → <strong>
    - *italic* or _italic_ → <em>
    - ==highlight== → <mark> (yellow)
    - g==highlight== → <mark class="mark-green"> (green)
    - r==highlight== → <mark class="mark-red"> (red)
    - c==citation== → <mark class="mark-citation"> (stone)

    HTML is escaped first to prevent XSS.
    """
    if not text:
        return ""

    # Escape HTML first
    text = escape(text)

    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)

    # Italic: *text* or _text_ (but not inside words for underscore)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<em>\1</em>", text)

    # Colored highlights: g==text==, r==text==, c==text== → <mark class="mark-{color}">
    text = re.sub(r"g==(.+?)==", r'<mark class="mark-green">\1</mark>', text)
    text = re.sub(r"r==(.+?)==", r'<mark class="mark-red">\1</mark>', text)
    text = re.sub(r"c==(.+?)==", r'<mark class="mark-citation">\1</mark>', text)
    # Default highlight: ==text== → <mark> (yellow)
    text = re.sub(r"==(.+?)==", r"<mark>\1</mark>", text)

    return mark_safe(text)
