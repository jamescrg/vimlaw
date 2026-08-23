# Agentic chat

The case AI chat has two modes, chosen when a conversation is created
(`Conversation.kind`, fixed for its life like the model):

- **Classic** (`kind="classic"`): the original single completion over a
  preloaded matter context (`context.assemble_matter_context_with_selection`
  and the Gemini Flash selector).
- **Agentic** (`kind="agent"`): a tool loop. The model gets a small,
  cache-stable orientation and read-only tools, decides which materials to
  open, and narrates as it goes. Modeled on how a coding agent works a
  repository: index first, read what matters, answer.

Both modes share the window, the 1s status poll, cancellation, message
creation, and the fenced-block writes (`tasks.finalize_response`). Intake
and agenda chats stay classic.

## Flow

```
new-conversation modal (Classic | Agentic) -> ?kind=agent -> hidden form field
send_message (kind on create only) -> daemon thread -> tasks.process_ai_request
  -> kind == "agent": agent.run_agent_request
       system   = agent_prompt.build_agent_system     two segments, see below
       history  = agent_prompt.build_agent_history    answers only + earlier-reads note
       tools    = agent_tools.build_agent_tools
       executor = agent_tools.make_agent_executor     budget, dedupe, parallel batches
       loop     = anthropic_client.send_to_claude_with_tools
                | gemini_client.send_to_gemini_with_tools
       status   = agent_state.AgentStatusWriter -> ai_status_<id> (full state every write)
       finish   = tasks.finalize_response             draft edits, facts, witnesses,
                                                      notes, handle links, citations
       payload  = complete {response, input_tokens, output_tokens, citations,
                            activity_log, agent_run}
views.ai_status -> status.html (+ agent-status.html) -> Message(agent_run=...)
messages.html / message-single.html -> agent-trail.html above the answer
```

Runs live on a daemon thread in the gunicorn worker like every chat turn,
so a deploy or a `.py` reload kills them mid-run (the heartbeat in
`status.py` reports it). Agent runs are minutes long; that caveat bites
harder here. Reloading the window mid-run re-attaches the poller
(`conversation_view` checks the status key), so a run that finished
unwatched is still collected.

## Orientation (`agent_prompt.py`)

Segment A, byte-stable across turns while the matter is unchanged (so the
provider cache keeps hitting):

1. `docs/ai-prompt.md` (the legal instructions, jurisdiction substituted)
2. the working method (orient from the index, read before relying, pinned
   first, batch independent reads, budget, one-sentence narration before
   each batch, answer rules)
3. `SOURCE_LINKING` (the citing rules)
4. the matter overview, contacts, witnesses, proceedings
5. highlights and timeline inline when their combined text is under 40k
   chars, otherwise pointer lines to `read_matter_section`
6. the material index: every readable item as one line (handle, name,
   category, date, size, importance, pinned) grouped by kind. Over 120k
   chars it drops descriptions, then collapses the conversation and
   invoice groups to counts.

Segment B, per turn: today's date and requester (`build_request_info`),
any armed write protocols (`tasks.armed_write_protocols`), a linked draft.

`build_manifest(include_always=True)` feeds the index: "always" items are
listed too, flagged pinned; "never" items stay hidden. `ManifestItem`
carries `handle` (`doc:12`, `thread:<id>`, `note:5`, `lib:9`, `case:3`,
`conv:8`, `inv:4`), `pinned` and `size_chars` for it.

**Prior turns' tool calls are not replayed.** The history is the
conversation's user messages and answers; a system note on the newest
message lists what earlier turns read (from prior `Message.agent_run`
steps) and says the text is not in the prompt. Bounded prompt, stable
cache prefix, no signed thinking blocks or `thought_signature`s to
persist. The cost: a follow-up may re-read a document.

## Tools (`agent_tools.py`)

All read-only; results are JSON objects and every one carries
`budget: {calls_left, chars_left}`. Text reads take `offset` and
`max_chars` (default 60k, cap 150k) and report `total_chars`,
`next_offset`, `truncated`.

| tool | reads |
|---|---|
| `search_materials` | watson full text over documents, highlights, facts, matter notes, library notes (scoped to the matter, `never` excluded) plus `icontains` over emails grouped by thread; hits already returned this turn are flagged `seen`, and a mostly-seen repeat gets a note |
| `read_document` | `Document.ocr_text` when OCR finished; `never` refused |
| `read_email_thread` | the thread via `format_email_thread`, `gmail_id` fallback |
| `read_note` | a matter note or a library note (`get_library_notes`) |
| `read_caselaw` | saved case notes, summary and the opinion (`_fetch_caselaw_opinion_text`, cached 1h) |
| `read_conversation` | an earlier conversation's transcript |
| `read_invoice` | `format_invoice` |
| `read_matter_section` | `apps.case.api.SECTIONS[section](matter)`, capped 150k |

Budget per turn (`AgentBudget`): 25 calls, 600k chars read, 30 model
turns, 4 parallel workers. Calls are reserved before dispatch under a
lock; an exact repeat of a call (same name and input) is served from the
run cache, uncharged, with a note. Once the budget is gone the executor
answers budget errors; after two batches of nothing but budget errors,
or at the turn ceiling, the loop appends a forced-answer note and makes
one last turn with tools disabled.

One model turn's calls run together (`run_tool_batch`, order preserved;
pool workers close their DB connection). Each call emits one step, first
pending then finalized, so the live log shows one row per tool.

## Provider loops

Same contract in both clients: `(system, messages, tools, execute_batch,
model, *, max_turns, is_cancelled, on_text, on_thinking, on_turn, on_note,
max_tokens) -> LoopResult`. Claude adds `effort`. The assistant turn is
echoed back verbatim (thinking blocks included on Claude, the original
`Part` objects on Gemini for their `thought_signature`); the tool results
go back as one user message in block order. Claude runs adaptive thinking
with the summary requested on Opus 4.8 (`agent_types`, `anthropic_client
._thinking_for`) and a rolling cache breakpoint on the newest block;
`TurnUsage.input` is the whole prompt with `cache_read` broken out beside
it so both providers report alike. A `max_tokens` tool turn is retried
once with a note; Gemini's `MALFORMED_FUNCTION_CALL` likewise; a Claude
`refusal` is terminal (`stop_details` stored).

Requires `anthropic>=1.0` (the 0.40 stream accumulator dropped thinking
blocks, which the loop must echo back).

## Status payload and the persisted run (`agent_state.py`)

Every write carries the whole state:

```
status, message, started_at, mode="agent",
activity_log: [str] (last 60),
usage: {input, output, cache_read, cache_write, turns, tool_calls,
        tool_calls_max, chars_read, chars_read_max, per_turn: [...]},
steps: [...] (last 60)
```

Steps, in display order per model turn: `text` (the model's prose,
updated in place while streaming), `turn` (written when the turn ends,
with its tokens), one `tool` per call, and `note` when the loop
intervened. Statuses: `context`, `thinking`, `generating`, `reading`,
`searching`, `applying`, `verifying` (all have icons in `status.html`).

On completion `Message.agent_run` holds `{version, llm, model,
elapsed_seconds, stop_reason, stop_details, forced_answer, usage, budget,
steps}` (the full step list); `input_tokens`/`output_tokens` on the
message are the cumulative totals. An error payload carries the partial
run so a failed turn stays inspectable. `research_trail` is untouched:
it belongs to the retired research chat's renderer.

## UI

- `templates/case/ai/new-conversation-modal.html`: Model, Mode (Classic |
  Agentic radio rows), Name. The last mode chosen is remembered per
  session (`ai_new_chat_kind`).
- `conversation-standalone.html`: hidden `kind` field, Agentic header
  badge; `table.html` shows the badge in the list.
- `status.html` includes `agent-status.html` for agent conversations: the
  typed rows (`agent-step.html`, stable ids for idiomorph) and the strip
  `1m 12s · 48.2k in · 3.1k out · 41k cached · 7/25 tools · 210k read`.
  The log pin yields to a reader who scrolled up.
- `agent-trail.html`: the same rows collapsed above the answer, totals
  in the summary. Filters in `apps/case/templatetags/ai_extras.py`.

## Tests

`apps/case/tests/test_agent_tools.py`, `test_agent_loop.py` (fake SDK
clients, no DB), `test_agent_prompt.py`, `test_agent_run.py` (fake loop,
real tools), `test_ai_extras.py`, plus the agent cases in
`test_views_ai.py` and `test_research_history.py`.
