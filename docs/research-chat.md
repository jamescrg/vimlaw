# Research Chat

The "research" chat mode (Conversation.kind) runs an agentic CourtListener
research loop instead of the classic single completion (shown as
"Analysis"). Analysis chats are untouched; the mode is chosen per turn via
a dropdown in the chat header (it posts with every send and send_message
persists it, so `kind` always holds the latest turn's mode). New chats
open in Analysis.

## Architecture

```
send_message (kind posted per turn; persisted on the conversation)
  -> process_ai_request           three-line dispatch at the top
    -> run_research_request       apps/case/ai/research_chat.py
        system = matter context + research prompt
                 (strategy announcement, CourtListener syntax rules,
                  grounded-citation contract, effort directive)
        tools  = apps/case/ai/research_tools.py (per-effort)
        loop   = send_to_claude_with_tools  (anthropic_client)
              or send_to_gemini_with_tools  (gemini_client)
        tool events -> update_status (live "Searching:/Reading:" in the
                       1s status poll) + trail events
        grounding: [cluster:n] markers resolved against the trail,
                   stripped from display, annotate verified_citations
        completion payload += research_trail -> Message.research_trail
```

The trail renders as a collapsible section under the answer
(templates/case/ai/research-trail.html), each case linking to the
cluster viewer. Claim-support vetting (vet_citations) runs unchanged.

## Effort budgets (research_tools.EFFORT_BUDGETS)

Formerly "depth" (quick/standard/deep); renamed low/medium/high with
migration case.0075.

| effort | tool calls | search page | read cap | treatment tool | plan first | total text cap |
|---|---|---|---|---|---|---|
| low | 5 | 6 | 20k chars | no | no | 120k chars |
| medium | 12 | 8 | 30k | yes | no | 300k |
| high | 25 | 10 | 40k | yes | yes | 600k |

The search page is the default; the model may request up to
MAX_SEARCH_RESULTS (20) per search when a survey needs more. Tool
results are resent every model turn, so the total text cap is the
token-cost lever. That cost profile is also why research turns are
Gemini-only: the Claude options are disabled (labelled "Analysis only")
while the mode dropdown reads Research, and send_message /
set_conversation_llm enforce it server-side.

## Search strategy

The survey protocol is library-first (secondary sources before primary,
the classic research structure): on a new question the model checks the
FIRM LIBRARY listing (free — it sits in the system prompt), reads the
relevant notes, and mines them for two things — the courts' vocabulary,
which seeds its search terms, and the notes' cited authorities, which
seed its reading list. Seeds are verified live (read + check_treatment;
notes are a map, not authority) and crawled: find_citing_cases forward
to the current statement, lookup_citation backward to the rule's
foundation. The doctrinal survey then fills gaps (full survey when the
library has nothing on point). The adverse-authority search is
deliberately independent of the library — a note records the firm's own
position. Specific-case questions, follow-ups, and explicit "search the
caselaw" requests skip the library pass.

Within searches the prompt encodes narrow-first triangulation: specific
doctrinal queries, two or three rephrasings before any broadening
(vocabulary mismatch is the usual failure, and searches are cheap while
reads are expensive), scatter handled by narrowing or by one deeper
result list instead of repeated near-identical queries. Citation
chasing runs both directions: lookup_citation walks backward to the
authorities an opinion rests on; find_citing_cases (tool-side
`cites:(cluster_id)` query, optionally AND-filtered) walks forward from
a seminal case to the current statement of the rule. A LEARNED
VOCABULARY rule has the model re-search with the courts' own terms of
art once its reads teach it better language.

## Firm library

Every standalone note (the whole Library tree, see
apps/notes/models.get_library_notes) is listed in a FIRM LIBRARY
section of the system prompt (research_chat.build_library_section: id,
folder path, title, summary excerpt) and readable via the
read_library_note tool at every effort level. Reads count against the same
read/total char caps as opinions; the trail shows a library_read event
linking to the note. The prompt frames library notes as internal work
product: consult before external search, never citable, no [cluster:n]
markers. The listing sits in the stable prefix, so prompt caching still
covers it across tool turns.

## Grounded-citation contract

Research answers may cite ONLY retrieved opinions and must tag each
citation `[cluster:12345]`. Markers are parsed (grounding pass in
research_chat.apply_grounding), matched against the trail, then stripped.
A citation the model produced from memory degrades to grounded=False and
an ungrounded warning in the trail; it never fails the response.

## CourtListener quotas

All CL calls go through apps/case/courtlistener_throttle.throttled_request:
process-wide 0.25s spacing, Retry-After/exponential backoff on 429, one
5xx retry. citation-lookup is the tight endpoint (60/min) and is shared
with classic citation verification.

## Adding a tool

1. Append a spec in research_tools.build_tools (name, description,
   input_schema) — both provider loops translate it automatically.
2. Add a handler in make_executor returning (payload_dict, trail_event).
3. Render the new event type in research-trail.html.
4. Mention it in the prompt (research_chat.PROMPT_ROLE) if the model
   should be steered toward it.

## v2 notes

- Save-to-matter from the trail (reuse caselaws_save).
- Statute retrieval tool.
- Phase out classic once research proves superior (kind default flip).
- search_library tool (watson full-text over library notes) if the firm
  library outgrows a listable size (~500 notes); today the full listing
  is ~10k tokens and cheaper than tool round-trips.
