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

1. **Refine** (`_refine_and_pause`, flash): first a library-mining pass
   (`_mine_library`) picks up to 2 firm-library notes whose text feeds
   the proposal (statutes, terms of art, key cases — the retired chat's
   library-pass advantage). Then the refiner proposes **3-5 labeled
   query VARIANTS** (Colloquial / Statutory / Doctrinal / Broad), eager
   about code sections — one variant centers on the governing statute's
   bare number. The prompt carries COURTLISTENER_SYNTAX_RULES,
   QUERY_DESIGN_RULES, and the procedural-vehicle rule. Pauses at
   status=refined; the approval screen shows each variant as a checkbox
   + editable text row, so the user prunes, edits, or composes the set.
2. **Search** (`_process_query`): every selected variant runs twice —
   a relevance page (score desc, 15) plus a thin newest-first slice
   (dateFiled desc, 8) that rescues recent opinions CL's score
   disfavors. All results merge, deduped by cluster, each case recording
   `hit_count` / `matched_variants` — a case surfaced by several
   differently-worded queries is a strong free relevance signal.
   Searches are the cheap lever (one credit each); the expensive stages
   stay hard-capped.
3. **Triage** (flash, snippet-only): each candidate gets a 0-10 promise
   score plus reason from CL's keyword-context snippet (missing snippet
   scores a neutral 5 — slip opinions have none). Below 3 =
   relevance=rejected WITH the reason — nothing is deleted.
4. **The selection gate** (status=selecting, `case-selection.html`): the
   second human checkpoint, mirroring the variant gate — reads are the
   expensive stage, so the user picks which cases get pulled. The card
   shows every candidate with its pre-read signals (citation/court/date,
   cite count, "Matched N queries", promise score, triage reason); the
   pipeline's own pick (`recommended`: top-BRIEF_MAX by hit_count →
   promise → CL order, with a 3-newest recency swap, via
   `_rank_candidates`) arrives prechecked, and ruled-out rows are
   selectable too so a wrong triage call can be overridden. Waits
   indefinitely (never reaped, like "refined"); unselected candidates
   become "Not selected" and stay briefable via the per-card button.
5. **Brief** (`_run_brief_phase` → `_brief_result`, flash): each selected
   case is briefed from its ENTIRE cluster — every sub-opinion concatenated,
   250k cap — using the structured abstract prompt in briefing.py
   (CASE/POSTURE/VEHICLE/HOLDING-verbatim/RELEVANCE/CAUTIONS/SCOPE +
   parseable RELEVANCE VERDICT and KEY AUTHORITIES). The verdict maps to
   relevance high/medium/low; the brief, rationale, and key authorities
   are stored on the row.
6. **Enrich** (`_run_enrichment`, chained qcluster task): forward
   `cites:()` searches from the 1-2 strongest HIGH cases (how slip
   opinions get found when they cite the line) and backward
   `lookup_citation` of the authorities the HIGH briefs rest on. NOTE:
   `cites:()` takes OPINION ids, never cluster ids — `cites:(cluster_id)`
   silently returns zero results (verified live 2026-08-17). New clusters join as rows
   with provenance badges ("Citing case" / "Cited authority") and get
   the same full-opinion briefs.
7. **Treatment**: `check_negative_treatment` on every HIGH row.
8. **Answer** (`_generate_final_answer`, gemini-pro-latest): direct
   answer first (naming the exact vehicle), then per-case discussions
   under 200 words each, vehicle-matched; slip opinions / zero-cite
   cases flagged "new and not yet settled law"; unchecked or negative
   treatment noted.

## Budgets (tasks.py constants)

~50 CourtListener requests per typical run, spaced by the 0.25s
throttle: 2 searches per variant (typically 6-8 total) + ≤15 briefs
(cluster+opinions) + 2 citing searches + ≤4 chased briefs + ≤4 lookups
+ treatment walks. ~55 flash calls + 1 pro call.

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
Emory University (June 2026 slip op, cluster 10875036, OCGA 9-11-37)
with a HIGH brief quoting the holding, flags its slip status, and
answers on the right vehicle.

Lesson from the first benchmark run (query 32, 2026-08-17): the refined
query required the phrase "motion to compel" — and Birg's opinion never
uses the word "compel" at all (it says "9-11-37" 14 times). A required
colloquial phrase group makes such a case unfindable by BOTH the
relevance page and the date slice; the statute number must ride as an
OR-alternative inside that group (the STATUTE NUMBER AS A HOOK rule in
briefing.py). `"9-11-37" AND "attorney fees" AND moot*` puts Birg in
the top 5 by relevance. The forward chase also could not have rescued
that run: Birg cites none of the compel-phrase cluster's cases.

Tests: apps/case/tests/test_research_pipeline.py (+ test_treatment.py).
