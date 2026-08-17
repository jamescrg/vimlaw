# Research Tab Pipeline

The matter Research tab is THE research surface (the AI-chat research mode
is retired; see research-chat.md). Its architecture: one user-approved
search, then a deterministic pipeline in which the model makes only
bounded judgments. Upgraded 2026-08-17 on feat/retire-research-chat to
close the quality gap with the retired chat — the failure being chased:
a June-2026 slip opinion (no syllabus, no reporter citation, ~zero cite
count) answering a fee-shifting question was invisible to the old
snippet/8k-excerpt pipeline.

## Flow

1. **Refine** (`_refine_and_pause`, flash): the question becomes ONE
   CourtListener query. The prompt carries COURTLISTENER_SYNTAX_RULES,
   QUERY_DESIGN_RULES, and the procedural-vehicle rule (never blend
   37(d)-style vehicles into a 37(a)(4)-style question). Pauses at
   status=refined; the user reviews and can EDIT the query, then confirms.
2. **Search** (`_process_query`): the approved query runs twice — the
   relevance page (score desc, 20) plus a newest-first slice of the SAME
   query (dateFiled desc, 10) that rescues recent opinions CL's score
   disfavors. Merged and deduped; date-only rows are tagged "Recent" and
   get guaranteed brief slots.
3. **Triage** (flash, snippet-only, inclusive): clearly-unrelated rows
   become relevance=rejected WITH the model's reason — nothing is
   deleted; they render in the collapsed "Ruled out" section.
4. **Brief** (`_brief_result`, flash): each surviving case (≤BRIEF_MAX)
   is briefed from its ENTIRE cluster — every sub-opinion concatenated,
   250k cap — using the structured abstract prompt in briefing.py
   (CASE/POSTURE/VEHICLE/HOLDING-verbatim/RELEVANCE/CAUTIONS/SCOPE +
   parseable RELEVANCE VERDICT and KEY AUTHORITIES). The verdict maps to
   relevance high/medium/low; the brief, rationale, and key authorities
   are stored on the row.
5. **Enrich** (`_run_enrichment`, chained qcluster task): forward
   `cites:(cluster_id)` searches from the 1-2 strongest HIGH cases (how
   slip opinions actually get found) and backward `lookup_citation` of
   the authorities the HIGH briefs rest on. New clusters join as rows
   with provenance badges ("Citing case" / "Cited authority") and get
   the same full-opinion briefs.
6. **Treatment**: `check_negative_treatment` on every HIGH row.
7. **Answer** (`_generate_final_answer`, gemini-pro-latest): direct
   answer first (naming the exact vehicle), then per-case discussions
   under 200 words each, vehicle-matched; slip opinions / zero-cite
   cases flagged "new and not yet settled law"; unchecked or negative
   treatment noted.

## Budgets (tasks.py constants)

~46 CourtListener requests per typical run, spaced by the 0.25s
throttle: 2 searches + ≤15 briefs (cluster+opinions) + 2 citing searches
+ ≤4 chased briefs + ≤4 lookups + treatment walks. ~50 flash calls + 1
pro call.

## Infrastructure

- Runs on **qcluster** (async_task, group "research"), two chained tasks
  per run to stay inside Q_CLUSTER's 600s timeout. **Restart qcluster
  after deploying changes to this module.**
- Heartbeat: `_update_query` bumps `ResearchQuery.updated_at` on every
  status write; `reap_stale_queries` (called from the tab views) flags
  runs stranded >30 min as errors. status=refined never reaps (it waits
  on the user).
- Bookmarking builds the CaseLaw row from `fetch_cluster` on the
  result's cluster_id, so citation-less slip opinions save (the cluster
  JSON's `court` field is an API URL — display name comes from the
  result, court_id from the URL tail).
- Jurisdictions: Federal adds the state's district courts (Georgia:
  gand/gamd/gasd — other states filled as needed), the home circuit,
  and SCOTUS.

## Benchmark

The acceptance question: "If I file a motion to compel and the other
side supplements their responses to moot the motion, can I still seek
attorney fees?" (Georgia + Federal). A passing run surfaces Birg v.
Emory (June 2026 slip op, OCGA 9-11-37(a)(4)) with a HIGH brief quoting
the holding, flags its slip status, and answers on the right vehicle.

Tests: apps/case/tests/test_research_pipeline.py (+ test_treatment.py).
