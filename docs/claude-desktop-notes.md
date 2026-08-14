# Claude Desktop access to Kosmos

Claude Desktop on a user's own machine can work with Kosmos directly:
read the notes Library and, for any open matter the user can access, the
full record (notes, contacts, rates, activity, events, tasks,
proceedings, settlement, documents, highlights, timeline, witnesses,
synced emails). Writes are narrow and deliberate: append/replace on
notes whose editor AI-write toggle is on, and create-only timeline
facts, witnesses, and tasks. Access is per-user: it authenticates with
the same `CompanionToken` the LibreOffice companion uses (header
`X-Kosmos-Token`), so a user's Claude sees exactly what that user can
see, and deactivating the user kills the token.

Three pieces:

- **JSON APIs** (`kosmos_api_auth` in `apps/drafts/api_auth.py`):
  - `apps/notes/api.py`, routed under `notes/api/`: `matters/?q=`,
    `notes/?scope=`, `notes/<id>/`, `search/?q=&scope=&limit=` (default
    20 per band, max 100), and the one note write path
    `notes/<id>/write/` (POST append/replace, gated per note by
    `Note.ai_write_until`). Scopes are `all | library | matters |
    matter:<id>`, restricted to open matters. Ranking and scope parsing
    are shared with the Ctrl+K palette so the two surfaces cannot drift.
  - `apps/case/api.py`, routed under `case/api/`: `matter/<id>/<section>/`
    serves 13 sections as AI-ready text (reusing the in-app chat's
    formatters from `apps/case/ai/context.py` where they exist);
    `documents/<id>/` and `matter/<id>/emails/<thread_id>/` serve full
    content; POSTs to `matter/<id>/facts/`, `matter/<id>/witnesses/`,
    and `tasks/` create rows through the same validated entry creators
    the in-app AI's fenced blocks use.
- **MCP server** (`tools/kosmos_notes_mcp.py`): a single-file stdio
  translator (the mcp SDK's MCPServer, the FastMCP successor) that
  Claude Desktop launches itself. Tools: `find_matter`, `list_library`,
  `list_matter_notes`, `search_notes`, `read_note`, `read_matter`,
  `read_document`, `read_email_thread`, `write_note`, `add_fact`,
  `add_witness`, `add_task`. Long reads truncate at 40k chars with an
  explicit marker. All intelligence lives in the APIs; the script only
  formats.
- **Settings page** (Settings → Claude Desktop, `apps/settings/claude/`):
  renders the exact `claude_desktop_config.json` block with the user's
  real token substituted (the `.oxt` precedent, generalized), serves the
  script for download, and offers rotate/revoke. Rotating re-keys the
  LibreOffice companion too — same token.

## Write access

Three write surfaces, all create-or-append, none destructive:

- **Notes**: `write_note` appends to (default) or replaces one note's
  markdown. It works only while that note's AI button in the editor
  toolbar (the sparkles icon) is switched on — a per-note grant stored
  as a 24-hour expiry timestamp (`Note.ai_write_until`), toggled off by
  a second click and self-expiring otherwise. The grant is per note and
  note-wide (any user's Claude with access to the note may write while
  it is on), because the MCP API is stateless token auth: there is no
  browser session to consult, so the note itself carries the grant.
  Writes land in the note's history like any other edit, and an open
  editor detects them through the normal conflict machinery. Claude
  cannot create or delete notes.
- **Timeline facts and witnesses**: `add_fact` / `add_witness` reuse
  `_create_fact_from_entry` and `_create_witness_from_entry`
  (validation, matter scoping of cited ids, name dedup) — exactly what
  the in-app chat's fenced blocks can do, no more.
- **Tasks**: `add_task` reuses `create_task_from_ai_entry`, assigned to
  the token's user; the API authorizes the matter itself (the service
  resolves by name without an access check).

## User setup

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/).
2. In Kosmos: Settings → Claude Desktop → download `kosmos_notes_mcp.py`,
   save it somewhere permanent.
3. In Claude Desktop: Settings → Developer → Edit Config. This opens
   `claude_desktop_config.json` — note this is Claude **Desktop's**
   config, not Claude Code's `CLAUDE.md`/`.mcp.json`, and Desktop
   pre-populates it with defaults. The block on the Kosmos settings page
   is the `"mcpServers"` member only: paste it inside the file's
   outermost braces as an additional top-level entry (comma after the
   preceding entry), keeping what's already there, then fix the script
   path. If an `mcpServers` section already exists, add just the
   `"kosmos"` entry inside it.
4. Restart Claude Desktop; the kosmos tools appear under the tools icon in
   the chat input.

## Scoping a Desktop Project to a matter

Desktop's MCP config is global — a Project cannot launch a different
server or pass different env. Matter scoping is conversational: the tools
take the matter as a parameter, and a per-matter Desktop Project carries
it in its custom instructions, e.g.:

> This project concerns the Kosmos matter "Gignilliat Tilton". Resolve it
> once with find_matter, then pass its matter_id to the read_matter,
> search_notes, and add_fact tools.

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
