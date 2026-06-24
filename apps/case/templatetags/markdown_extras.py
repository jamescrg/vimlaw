import re

import markdown
from django import template
from django.utils.safestring import mark_safe
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

from apps.case.notes.markdown_ext import NoteReferenceExtension

register = template.Library()


# --- Bluebook ellipses (Rule 5.3) -------------------------------------------
# Normalise any ellipsis — a unicode "…", three-or-more periods, or already-
# spaced dots — to the Bluebook form of space-separated periods: ". . ." mid-
# sentence, ". . . ." when a fourth (sentence-terminating) period is present.
# Regular spaces, so it may wrap. Runs as a tree-processor so it never touches
# code spans/blocks (where "..." is meaningful, e.g. spread/rest operators).
_ELLIPSIS_RE = re.compile(r"[ \t]*(…\.?|\.(?:[ \t]*\.){2,})[ \t]*")


def _to_bluebook_ellipsis(match):
    run = match.group(1)
    dots = run.count(".") + (3 if "…" in run else 0)
    dots = 4 if dots >= 4 else 3
    return " " + " ".join(["."] * dots) + " "


def _normalize_ellipses(text):
    if not text or ("." not in text and "…" not in text):
        return text
    return _ELLIPSIS_RE.sub(_to_bluebook_ellipsis, text)


class _BluebookEllipsisTreeprocessor(Treeprocessor):
    def run(self, root):
        for el in root.iter():
            # An element's .text is its own content (skip code); its .tail is the
            # prose that follows it in the parent, which is always fair game.
            if el.text and el.tag not in ("code", "pre"):
                el.text = _normalize_ellipses(el.text)
            if el.tail:
                el.tail = _normalize_ellipses(el.tail)
        return root


class BluebookEllipsisExtension(Extension):
    def extendMarkdown(self, md):
        md.treeprocessors.register(
            _BluebookEllipsisTreeprocessor(md), "bluebook_ellipsis", 5
        )


class NoIndentedCodeExtension(Extension):
    """Disable Markdown's indented (4-space) code blocks. AI responses that echo
    pasted, indented text — e.g. bulleted lists — were being turned into code
    blocks (a jarring monospace panel). Fenced ``` blocks still render as code,
    so real code is unaffected."""

    def extendMarkdown(self, md):
        md.parser.blockprocessors.deregister("code")


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

    # Convert backtick-wrapped case names to italics
    # AI sometimes uses `Case v. Name` instead of *Case v. Name*
    # Pattern matches: `Something v. Something` or `Something v Something`
    text = re.sub(
        r"`([A-Z][^`]*?\s+v\.?\s+[A-Z][^`]*?)`",
        r"*\1*",
        text,
    )

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
            "pymdownx.mark",
            "smarty",
            BluebookEllipsisExtension(),
            NoIndentedCodeExtension(),
            NoteReferenceExtension(),
        ],
        extension_configs={
            # Curl quotes/apostrophes for clean copy-paste. Dashes and ellipses
            # are left to smarty's defaults off — ellipses are handled by the
            # Bluebook tree-processor instead. smarty skips code.
            "smarty": {
                "smart_quotes": True,
                "smart_dashes": False,
                "smart_ellipses": False,
            },
            # Don't let adjacent punctuation/brackets suppress a ==highlight==;
            # smart_mark's flanking rules otherwise drop marks next to "(", ".",
            # quotes, etc.
            "pymdownx.mark": {"smart_mark": False},
        },
    )
    return mark_safe(md.convert(text))
