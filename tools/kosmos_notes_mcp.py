# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp"]
# ///
"""Kosmos MCP server for Claude Desktop.

A deliberately thin stdio translator: every tool is one HTTP call against
the token-authed JSON APIs in Kosmos (apps/notes/api.py for notes,
apps/case/api.py for the matter record), which own all access control,
ranking, and formatting. Reads cover notes plus every section of a
matter; writes are narrow: append/replace on notes whose editor AI-write
toggle is on (a 24-hour grant), and create-only timeline facts,
witnesses, and tasks.

Claude Desktop launches this script itself; configure it in
claude_desktop_config.json (this is Claude DESKTOP's config, not
CLAUDE.md / .mcp.json, which belong to Claude Code):

    {
      "mcpServers": {
        "kosmos": {
          "command": "uv",
          "args": ["run", "--script", "/path/to/kosmos_notes_mcp.py"],
          "env": {
            "KOSMOS_URL": "https://kosmos.craiglegal.law",
            "KOSMOS_TOKEN": "<your token from Kosmos settings>"
          }
        }
      }
    }

The Kosmos settings page (Settings -> Claude Desktop) renders this block
with your real token filled in.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from mcp.server import MCPServer

KOSMOS_URL = os.environ.get("KOSMOS_URL", "https://kosmos.craiglegal.law").rstrip("/")
KOSMOS_TOKEN = os.environ.get("KOSMOS_TOKEN", "")

READ_TRUNCATE_CHARS = 40_000

MATTER_SECTIONS = (
    "overview",
    "contacts",
    "rates",
    "activity",
    "events",
    "tasks",
    "proceedings",
    "settlement",
    "documents",
    "highlights",
    "timeline",
    "witnesses",
    "emails",
)

mcp = MCPServer("kosmos-notes")


def _request(path, payload=None, **params):
    """Call a Kosmos API endpoint (GET, or POST when payload is given).

    path is root-relative (notes/api/... or case/api/...). API error
    bodies are raised as tool errors verbatim: the 401 body tells the
    user how to reissue a token and the note-write 403 explains the
    editor toggle, so both must reach the conversation.
    """
    url = f"{KOSMOS_URL}/{path}"
    query = {k: v for k, v in params.items() if v is not None and v != ""}
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = {"X-Kosmos-Token": KOSMOS_TOKEN}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.load(exc)["error"]
        except Exception:
            detail = exc.reason
        raise RuntimeError(f"Kosmos API error ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach Kosmos at {KOSMOS_URL}: {exc.reason}"
        ) from exc


def _get(path, **params):
    return _request(path, **params)


def _post(path, payload):
    return _request(path, payload=payload)


def _truncate(content):
    if len(content) <= READ_TRUNCATE_CHARS:
        return content
    total = len(content)
    return (
        content[:READ_TRUNCATE_CHARS]
        + f"\n\n[truncated at {READ_TRUNCATE_CHARS:,} characters; {total:,} total]"
    )


def _manifest(notes):
    if not notes:
        return "No notes found."
    lines = []
    for note in notes:
        line = f"- [id {note['id']}] {note['path']} (updated {note['updated_at'][:10]})"
        if note.get("summary"):
            line += f": {note['summary']}"
        lines.append(line)
    return "\n".join(lines)


@mcp.tool()
def find_matter(query: str) -> str:
    """Find open Kosmos matters by name (case-insensitive contains match).

    Use this once to resolve a matter name (e.g. from the project
    instructions) to its matter_id, then pass that id to the other
    matter tools. Returns each match as its id and full name.
    """
    matters = _get("notes/api/matters/", q=query)["matters"]
    if not matters:
        return f"No open matters match {query!r}."
    return "\n".join(f"- [id {m['id']}] {m['name']}" for m in matters)


@mcp.tool()
def list_library() -> str:
    """List the general notes Library (notes not tied to any matter).

    Returns one line per note: id, folder path, last-updated date, and a
    short summary when one exists. Use read_note with an id to read one.
    """
    return _manifest(_get("notes/api/notes/", scope="library")["notes"])


@mcp.tool()
def list_matter_notes(matter_id: int) -> str:
    """List all notes belonging to one matter (resolve the id with
    find_matter first).

    Returns one line per note: id, path, last-updated date, and a short
    summary when one exists. Use read_note with an id to read one.
    """
    return _manifest(_get("notes/api/notes/", scope=f"matter:{matter_id}")["notes"])


@mcp.tool()
def search_notes(query: str, matter_id: int | None = None, limit: int = 20) -> str:
    """Search notes by title/path and full text (two ranked bands).

    Scoped to one matter's notes when matter_id is given; otherwise spans
    the Library plus every matter the user can access. Content matches
    include an excerpt with the match wrapped in **. limit caps each band
    (max 100). Use read_note to read a result in full.
    """
    scope = f"matter:{matter_id}" if matter_id is not None else "all"
    result = _get("notes/api/search/", q=query, scope=scope, limit=limit)
    sections = []
    if result["title_matches"]:
        sections.append(
            "Title/path matches:\n"
            + "\n".join(
                f"- [id {n['id']}] {n['path']}" for n in result["title_matches"]
            )
        )
    if result["content_matches"]:
        sections.append(
            "Content matches:\n"
            + "\n".join(
                f"- [id {n['id']}] {n['path']}: {n['excerpt']}"
                for n in result["content_matches"]
            )
        )
    return "\n\n".join(sections) or f"No notes match {query!r}."


@mcp.tool()
def read_note(note_id: int) -> str:
    """Read one note in full (markdown), by the id shown in listings and
    search results.

    The header gives the note's path and last-updated time; cite the note
    by its title/path when you use it. Very large notes are truncated,
    with an explicit marker saying so.
    """
    note = _get(f"notes/api/notes/{note_id}/")
    return (
        f"# {note['title']}\n"
        f"Path: {note['path']}\n"
        f"Updated: {note['updated_at']}\n\n"
        f"{_truncate(note['content'])}"
    )


@mcp.tool()
def write_note(note_id: int, content: str, mode: str = "append") -> str:
    """Write to one note: mode "append" adds the content as new
    paragraphs after the existing text, "replace" overwrites the whole
    note. Content is plain markdown. Notes cannot be created or deleted.

    This edits the user's real note immediately; only call it when the
    user has explicitly asked for the write, and prefer append unless
    they clearly want a rewrite. Writing requires the note's AI-write
    toggle in the Kosmos editor (a 24-hour grant); if it is off the
    error explains how to enable it - relay that to the user verbatim.
    """
    result = _post(
        f"notes/api/notes/{note_id}/write/", {"content": content, "mode": mode}
    )
    return result["message"]


@mcp.tool()
def read_matter(matter_id: int, section: str) -> str:
    """Read one section of a matter's record (resolve the id with
    find_matter first).

    Sections: overview, contacts, rates (billing setup and hourly
    rates), activity (time entries, expenses, and flat fees with
    category coding), events, tasks (capped at 20), proceedings,
    settlement, documents (metadata manifest; use read_document for a
    document's full text), highlights (excerpts with [hl:ID] handles
    usable as add_fact sources), timeline (the facts chronology),
    witnesses, emails (thread manifest; use read_email_thread for a
    full thread).

    Start with overview; then read only the sections the question needs.
    """
    return _truncate(_get(f"case/api/matter/{matter_id}/{section}/")["text"])


@mcp.tool()
def read_document(document_id: int) -> str:
    """Read one document's extracted text, by the [doc:ID] id shown in
    the documents section.

    Returns the OCR/extracted text (scans with no text yet report their
    status instead). Very large documents are truncated, with an
    explicit marker saying so.
    """
    doc = _get(f"case/api/documents/{document_id}/")
    text = doc["text"] or f"(no extracted text; OCR status: {doc['ocr_status']})"
    return (
        f"# {doc['name']}\n"
        f"Matter: {doc['matter']}\n"
        f"Category: {doc['category']}, date: {doc['date'] or 'none'}\n\n"
        f"{_truncate(text)}"
    )


@mcp.tool()
def read_email_thread(matter_id: int, thread_id: str) -> str:
    """Read one synced email thread in full, by the thread id shown in
    the emails section.

    Messages are oldest-first and include any extracted attachment text.
    Very large threads are truncated, with an explicit marker saying so.
    """
    result = _get(f"case/api/matter/{matter_id}/emails/{thread_id}/")
    return _truncate(result["text"])


@mcp.tool()
def add_fact(
    matter_id: int,
    description: str,
    date: str | None = None,
    time: str | None = None,
    importance: int = 4,
    color: str | None = None,
    highlight_ids: list[int] | None = None,
    document_ids: list[int] | None = None,
) -> str:
    """Add one fact to a matter's timeline. Creates immediately; only
    call on the user's explicit direction, and read the timeline section
    first to avoid duplicating an existing fact.

    description is a terse noun-phrase headline (aim for 20-60
    characters; hard cap 150). date/time are ISO (YYYY-MM-DD, HH:MM);
    importance is 1-7 (4 = normal). Source the fact with highlight_ids
    ([hl:ID] from the highlights section, preferred) or document_ids
    ([doc:ID]); never cite both for the same source. Ids outside the
    matter are silently dropped.
    """
    result = _post(
        f"case/api/matter/{matter_id}/facts/",
        {
            "description": description,
            "date": date,
            "time": time,
            "importance": importance,
            "color": color,
            "highlights": highlight_ids or [],
            "documents": document_ids or [],
        },
    )
    return result["message"]


@mcp.tool()
def add_witness(
    matter_id: int,
    name: str,
    affiliation: str | None = None,
    alignment: str = "neutral",
    knowledge: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    address: str | None = None,
    importance: int = 4,
) -> str:
    """Add one witness to a matter. Creates immediately; only call on
    the user's explicit direction. A same-named witness already in the
    matter is reported instead of duplicated.

    affiliation is the party or faction they belong to; alignment is
    friendly, neutral, or hostile as seen from our client's side;
    knowledge summarizes what they can testify to. Never guess contact
    details (phone, email, address); leave them out unless the record
    states them. importance is 1-7 (4 = normal).
    """
    result = _post(
        f"case/api/matter/{matter_id}/witnesses/",
        {
            "name": name,
            "affiliation": affiliation,
            "alignment": alignment,
            "knowledge": knowledge,
            "phone": phone,
            "email": email,
            "address": address,
            "importance": importance,
        },
    )
    return result["message"]


@mcp.tool()
def add_task(
    description: str,
    matter_id: int | None = None,
    due: str | None = None,
    importance: int = 4,
) -> str:
    """Add one task, assigned to you-the-user's own account. Creates
    immediately; only call on the user's explicit direction.

    due is an ISO date (YYYY-MM-DD); importance is 1-7 (4 = normal).
    Pass matter_id to file the task under a matter, or omit it for a
    general Admin task.
    """
    result = _post(
        "case/api/tasks/",
        {
            "description": description,
            "matter_id": matter_id,
            "due": due,
            "importance": importance,
        },
    )
    return f"{result['message']} [{result['matter']}]"


if __name__ == "__main__":
    mcp.run()
