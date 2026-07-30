"""Gmail API message payload parsing.

Turns a ``users.messages.get(format="full")`` response into the fields the
``Email`` model stores: headers, an aware datetime, plain body text, and
attachment metadata. Bodies arrive base64url-encoded per MIME part; we walk
the part tree, prefer ``text/plain``, and fall back to a stdlib HTML-to-text
conversion for HTML-only messages (no new dependency).
"""

import base64
import html as html_module
import re
from datetime import (
    datetime,
    timezone as dt_timezone,
)
from html.parser import HTMLParser
from typing import NamedTuple


class ParsedEmail(NamedTuple):
    sender: str
    recipients: str
    subject: str
    date: datetime | None
    snippet: str
    body_text: str
    body_source: str  # "plain" | "html"
    attachments: list  # [{"filename", "mime_type", "size"}]


# --------------------------------------------------------------------------- #
# HTML → text
# --------------------------------------------------------------------------- #
_BLOCK_TAGS = {
    "p",
    "div",
    "br",
    "tr",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "table",
    "ul",
    "ol",
}
_SKIP_TAGS = {"style", "script", "head", "title"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._chunks = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self._chunks.append(data)

    def text(self):
        return "".join(self._chunks)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # Malformed HTML — fall back to a crude tag strip.
        return html_module.unescape(re.sub(r"<[^>]+>", " ", html)).strip()
    text = parser.text()
    # Collapse runs of blank lines and trailing whitespace per line.
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------- #
# Payload walking
# --------------------------------------------------------------------------- #
def _decode_body(part) -> str:
    data = part.get("body", {}).get("data")
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _walk_parts(part, found):
    """Recursively collect first plain body, first html body, attachments."""
    mime = part.get("mimeType", "")
    filename = part.get("filename") or ""

    if filename:
        found["attachments"].append(
            {
                "filename": filename,
                "mime_type": mime,
                "size": part.get("body", {}).get("size", 0),
            }
        )
    elif mime == "text/plain" and not found["plain"]:
        found["plain"] = _decode_body(part)
    elif mime == "text/html" and not found["html"]:
        found["html"] = _decode_body(part)

    for child in part.get("parts", []):
        _walk_parts(child, found)


def _header(headers, name):
    name = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name:
            return h.get("value", "")
    return ""


def parse_payload(msg: dict) -> ParsedEmail:
    """Parse a Gmail ``messages.get(format="full")`` response dict."""
    payload = msg.get("payload", {})
    headers = payload.get("headers", [])

    sender = _header(headers, "From")
    to = _header(headers, "To")
    cc = _header(headers, "Cc")
    recipients = ", ".join(part for part in (to, cc) if part)
    subject = _header(headers, "Subject")

    date = None
    internal = msg.get("internalDate")
    if internal:
        try:
            date = datetime.fromtimestamp(int(internal) / 1000, tz=dt_timezone.utc)
        except (ValueError, TypeError, OSError):
            date = None

    found = {"plain": "", "html": "", "attachments": []}
    _walk_parts(payload, found)

    if found["plain"]:
        body_text, body_source = found["plain"], "plain"
    elif found["html"]:
        body_text, body_source = html_to_text(found["html"]), "html"
    else:
        body_text, body_source = "", "plain"

    # Strip NULs — Postgres text columns reject them (same concern as the
    # OCR pipeline's sanitize step).
    body_text = body_text.replace("\x00", "")

    return ParsedEmail(
        sender=sender[:500],
        recipients=recipients,
        subject=subject[:998],
        date=date,
        snippet=html_module.unescape(msg.get("snippet", ""))[:500],
        body_text=body_text,
        body_source=body_source,
        attachments=found["attachments"],
    )
