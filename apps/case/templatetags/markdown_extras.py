import re

import markdown
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


def normalize_markdown(text):
    """
    Ensure blank lines before block elements so markdown parses correctly.
    AI responses often lack the blank line before lists, code blocks, etc.
    """
    # Add blank line before list items that follow non-blank lines
    text = re.sub(r"([^\n])\n([-*+] |\d+\. )", r"\1\n\n\2", text)
    # Add blank line before code fences
    text = re.sub(r"([^\n])\n(```)", r"\1\n\n\2", text)
    # Add blank line before headers
    text = re.sub(r"([^\n])\n(#{1,6} )", r"\1\n\n\2", text)
    return text


@register.filter
def render_markdown(text):
    """
    Render markdown text to HTML.
    """
    if not text:
        return ""

    text = normalize_markdown(text)

    md = markdown.Markdown(
        extensions=[
            "fenced_code",
            "tables",
            "nl2br",
        ]
    )
    return mark_safe(md.convert(text))
