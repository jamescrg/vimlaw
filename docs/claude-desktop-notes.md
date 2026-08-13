# Claude Desktop access to the notes library

Claude Desktop on a user's own machine can list, search, and read Kosmos
notes: the general Library plus any matter the user can access. Access is
strictly read-only (the in-app AI keeps the only note write path) and
per-user: it authenticates with the same `CompanionToken` the LibreOffice
companion uses (header `X-Kosmos-Token`), so a user's Claude sees exactly
what that user can see, and deactivating the user kills the token.

Three pieces:

- **JSON API** (`apps/notes/api.py`, routed under `notes/api/`): four
  GET endpoints — `matters/?q=`, `notes/?scope=`, `notes/<id>/`,
  `search/?q=&scope=&limit=` (default 20 results per band, max 100).
  Scopes are `all | library | matters | matter:<id>`, restricted to open
  matters (matching the editor tree). Ranking and scope parsing are shared
  with the Ctrl+K palette (`_parse_note_scope`, `_palette_search` in
  `apps/notes/views.py`), so the two surfaces cannot drift.
- **MCP server** (`tools/kosmos_notes_mcp.py`): a single-file stdio
  translator (FastMCP) that Claude Desktop launches itself. Tools:
  `find_matter`, `list_library`, `list_matter_notes`, `search_notes`,
  `read_note` (truncates past 40k chars with an explicit marker). All
  intelligence lives in the API; the script only formats.
- **Settings page** (Settings → Claude Desktop, `apps/settings/claude/`):
  renders the exact `claude_desktop_config.json` block with the user's
  real token substituted (the `.oxt` precedent, generalized), serves the
  script for download, and offers rotate/revoke. Rotating re-keys the
  LibreOffice companion too — same token.

## User setup

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/).
2. In Kosmos: Settings → Claude Desktop → download `kosmos_notes_mcp.py`,
   save it somewhere permanent.
3. In Claude Desktop: Settings → Developer → Edit Config. This opens
   `claude_desktop_config.json` — note this is Claude **Desktop's**
   config, not Claude Code's `CLAUDE.md`/`.mcp.json`. Paste the block from
   the Kosmos settings page, fixing the script path.
4. Restart Claude Desktop; the kosmos tools appear under the tools icon in
   the chat input.

## Scoping a Desktop Project to a matter

Desktop's MCP config is global — a Project cannot launch a different
server or pass different env. Matter scoping is conversational: the tools
take the matter as a parameter, and a per-matter Desktop Project carries
it in its custom instructions, e.g.:

> This project concerns the Kosmos matter "Gignilliat Tilton". Resolve it
> once with find_matter, then pass its matter_id to list_matter_notes and
> search_notes.

The Library is available in every conversation, which matches its purpose.

## Where this goes (rungs 2 and 3)

The API and tool semantics are the product; transport and auth are
packaging. Rung 2: package the same server as an MCP bundle (`.mcpb`) for
one-click Desktop install — Desktop ships a Node runtime, not Python, so
that client is a thin TypeScript port; keep the script dumb so the port
stays trivial. Rung 3: remote MCP (streamable HTTP) served by Django
itself behind OAuth 2.1 (django-oauth-toolkit; Claude accepts a manually
issued client id/secret, so dynamic client registration can wait) — no
local install, works on claude.ai web and mobile, offboarding is a
server-side revoke.
