# Research Chat (retired 2026-08-16)

The "research" chat mode ran an agentic CourtListener research loop
inside the AI chat (Conversation.kind = "research", chosen per turn from
a header dropdown, with a Model switcher and a Low/Medium/High Effort
dial beside it). It was retired on branch `feat/retire-research-chat`:
the loop proved hard to keep on the rails — test runs kept burning their
search budgets on redundant, rephrased queries, blending procedural
vehicles (motion-to-compel fee questions answered with sanctions cases),
and drifting off-point despite escalating prompt discipline and
mechanical guards (three budget pools, overlap suppression that withheld
repeated results, a read-and-abstract briefing agent).

All chats now run the classic Analysis path only, and the chat header
shows a static model badge (the model is chosen in the new-conversation
modal and fixed for the conversation's life).

## What was removed

- `apps/case/ai/research_chat.py` — the worker (survey-protocol prompt,
  effort directives, grounding of `[cluster:n]` markers, live log).
- `apps/case/ai/research_tools.py` — the tool layer (search/read/skim/
  abstract/citing/lookup/treatment/library tools, per-effort budgets).
- `send_to_claude_with_tools` / `send_to_gemini_with_tools` — the
  provider tool loops (research chat was their only caller).
- The header Mode/Model/Effort dropdowns, `set_conversation_llm`
  (`ai-set-llm`), and the per-turn `kind`/`effort` fields on the send
  form. `send_message` no longer reads either parameter.

Recoverable from git history at the tip of `dev` before this branch
(last shipped state: PR #517 plus the `feat/research-budget-raise`
follow-ups).

## What remains

- `Conversation.kind` / `effort` fields and their choices: historical
  data on old conversations (the AI list still badges old research
  conversations, and clones copy the fields).
- `Message.research_trail` and its renderers
  (`templates/case/ai/research-trail.html`, `authorities.html`,
  `Message.cited_authorities()`): old research answers keep their
  collapsible trail and Authorities section, with case links into the
  cluster viewer.
- The separate research pipeline app (`apps/case/research/`: saved case
  law, treatment checks, query syntax rules, the CourtListener throttle)
  and the cluster viewer — used by citation vetting and the matter
  research features, untouched.

Tests for the surviving behavior live in
`apps/case/tests/test_research_history.py` (history rendering, retired
controls) and `apps/case/tests/test_courtlistener_throttle.py`.

## Successor

The agentic chat mode (docs/agent-chat.md, 2026-08-23) is the tool-loop
successor: matter materials instead of CourtListener, chosen per
conversation instead of per turn.
