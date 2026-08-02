# Research Chat

The "research" chat style (Conversation.kind) runs an agentic CourtListener
research loop instead of the classic single completion. Classic chats are
untouched; the style is chosen per conversation in the new-conversation
modal and remembered per session.

## Architecture

```
send_message (kind=research on create)
  -> process_ai_request           three-line dispatch at the top
    -> run_research_request       apps/case/ai/research_chat.py
        system = matter context + research prompt
                 (strategy announcement, CourtListener syntax rules,
                  grounded-citation contract, depth directive)
        tools  = apps/case/ai/research_tools.py (per-depth)
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

## Depth budgets (research_tools.DEPTH_BUDGETS)

| depth | tool calls | search page | read cap | treatment tool | plan first | total text cap |
|---|---|---|---|---|---|---|
| quick | 5 | 4 | 20k chars | no | no | 120k chars |
| standard | 12 | 6 | 30k | yes | no | 300k |
| deep | 25 | 8 | 40k | yes | yes | 600k |

Tool results are resent every model turn, so the total text cap is the
token-cost lever. Deep on Claude Opus is dollars per question; Gemini is
far cheaper per token.

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
