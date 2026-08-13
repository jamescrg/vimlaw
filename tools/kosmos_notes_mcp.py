# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp"]
# ///
"""Kosmos notes MCP server for Claude Desktop.

A deliberately thin stdio translator: every tool is one GET against the
read-only notes API in Kosmos (apps/notes/api.py), which owns all access
control and ranking. Claude Desktop launches this script itself; configure
it in claude_desktop_config.json (this is Claude DESKTOP's config, not
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

mcp = MCPServer("kosmos-notes")


def _get(path, **params):
    """GET a notes-API endpoint, returning parsed JSON.

    API error bodies are raised as tool errors verbatim: the 401 body tells
    the user how to reissue a token, so it must reach the conversation.
    """
    url = f"{KOSMOS_URL}/notes/api/{path}"
    query = {k: v for k, v in params.items() if v is not None and v != ""}
    if query:
        url += "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(url, headers={"X-Kosmos-Token": KOSMOS_TOKEN})
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
    instructions) to its matter_id, then pass that id to list_matter_notes
    or search_notes. Returns each match as its id and full name.
    """
    matters = _get("matters/", q=query)["matters"]
    if not matters:
        return f"No open matters match {query!r}."
    return "\n".join(f"- [id {m['id']}] {m['name']}" for m in matters)


@mcp.tool()
def list_library() -> str:
    """List the general notes Library (notes not tied to any matter).

    Returns one line per note: id, folder path, last-updated date, and a
    short summary when one exists. Use read_note with an id to read one.
    """
    return _manifest(_get("notes/", scope="library")["notes"])


@mcp.tool()
def list_matter_notes(matter_id: int) -> str:
    """List all notes belonging to one matter (resolve the id with
    find_matter first).

    Returns one line per note: id, path, last-updated date, and a short
    summary when one exists. Use read_note with an id to read one.
    """
    return _manifest(_get("notes/", scope=f"matter:{matter_id}")["notes"])


@mcp.tool()
def search_notes(query: str, matter_id: int | None = None, limit: int = 20) -> str:
    """Search notes by title/path and full text (two ranked bands).

    Scoped to one matter's notes when matter_id is given; otherwise spans
    the Library plus every matter the user can access. Content matches
    include an excerpt with the match wrapped in **. limit caps each band
    (max 100). Use read_note to read a result in full.
    """
    scope = f"matter:{matter_id}" if matter_id is not None else "all"
    result = _get("search/", q=query, scope=scope, limit=limit)
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
    note = _get(f"notes/{note_id}/")
    content = note["content"]
    if len(content) > READ_TRUNCATE_CHARS:
        total = len(content)
        content = (
            content[:READ_TRUNCATE_CHARS]
            + f"\n\n[truncated at {READ_TRUNCATE_CHARS:,} characters; "
            f"{total:,} total]"
        )
    return (
        f"# {note['title']}\n"
        f"Path: {note['path']}\n"
        f"Updated: {note['updated_at']}\n\n"
        f"{content}"
    )


if __name__ == "__main__":
    mcp.run()
