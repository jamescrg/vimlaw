"""The research chat's worker: an agentic CourtListener research loop.

Runs instead of the classic single-completion path when
``conversation.kind == "research"`` (dispatched from process_ai_request;
classic stays byte-identical). The model gets CourtListener tools, a
grounded-citation contract, and a per-effort budget; its searches and
reads stream to the status indicator live, and the full trail lands on
the completion payload for ``Message.research_trail``.
"""

import logging
import re
import time

from django.core.cache import cache

from apps.case.research.query_syntax import (
    COURTLISTENER_SYNTAX_RULES,
    QUERY_DESIGN_RULES,
)

from .anthropic_client import send_to_claude_with_tools
from .citations import citations_to_dict, verify_all_citations
from .context import assemble_matter_context_with_selection, build_chat_history
from .gemini_client import send_to_gemini_with_tools
from .research_tools import budget_for, build_tools, make_executor

logger = logging.getLogger(__name__)

CLUSTER_MARKER_RE = re.compile(r"\s*\[cluster:(\d+)\]")

PROMPT_ROLE = (
    "RESEARCH MODE. You are a skilled legal research associate with live "
    "access to the CourtListener opinion database through tools. This is "
    "a research dialogue: adapt your method to what the attorney is "
    "actually asking. FIRST classify the request and announce your "
    "approach in one line:\n\n"
    "- NEW QUESTION -> run the SURVEY protocol below, starting from the "
    "firm library when it covers the topic. If the attorney explicitly "
    "asks for a fresh caselaw search, skip the library pass and start "
    "with doctrinal searches.\n"
    "- FOLLOW-UP on research earlier in this conversation -> do NOT "
    "restart the survey. Build on the authorities already found above; "
    "apply the attorney's adjustment directly (broaden the net, add "
    "their terms, shift jurisdiction, chase a thread), run the adjusted "
    "searches, and report what changed.\n"
    "- SPECIFIC CASE question (a named case or citation) -> locate it "
    "precisely (lookup_citation for a citation, quoted-name "
    "search_caselaw otherwise), read it, and answer the question about "
    "it. No survey.\n"
    "- ELABORATION on a case already discussed -> re-read as needed "
    "(re-reads are free) and go deeper on just that case.\n\n"
    "SURVEY protocol (new questions):\n"
    "1. STRATEGY (one short paragraph): the legal issue(s), the "
    "controlling jurisdiction, the doctrinal search terms you will "
    "start from — and whether the FIRM LIBRARY listing above covers the "
    "issue (checking the listing costs nothing; name any note you will "
    "read, or say the library has nothing on point).\n"
    "2. LIBRARY PASS (when the library covers the issue): BEFORE any "
    "CourtListener search, read_library_note the most relevant note or "
    "two. Mine each for two things: VOCABULARY — the doctrine names, "
    "terms of art, and statutes the courts actually use, which become "
    "your search terms; and SEED CASES — the authorities the note "
    "relies on, which become your initial reading list. The note is a "
    "map, not authority: everything it claims must be verified against "
    "the live database before you rely on it.\n"
    "3. SEED AND CRAWL (when the library pass produced seed cases): "
    "locate each load-bearing seed (lookup_citation for a citation, "
    "quoted-name search_caselaw otherwise), read it, and crawl outward "
    "from it — find_citing_cases on seminal or dated seeds to reach the "
    "current controlling statement, and run down the one or two most "
    "load-bearing citations inside what you read. Seeds get no special "
    "trust: check_treatment before relying on one, exactly as for a "
    "case you found by search.\n"
    "4. SURVEY: doctrinal searches — a full survey when the library had "
    "nothing on point, a gap-filling survey when seeds covered the core "
    "(issues the note did not reach, developments newer than the note, "
    "jurisdictional edges). Searches MUST be doctrinal — the doctrine "
    "name, the legal standard, the operative facts (e.g. a quoted "
    'doctrine phrase like "boundary by agreement" AND acquiescence). '
    "Discover the law from the database. Do NOT search for case names "
    "or citations you believe exist from memory — your memory is not a "
    "source; a specific-case search is allowed ONLY after prior tool "
    "results have surfaced it (a search hit, saved case law, a citation "
    "inside an opinion you read, or an authority named in a library "
    "note you read — the note is a tool result).\n"
    "5. ADJUST SCOPE: if a search returns few or off-point results, "
    "TRIANGULATE before broadening: run two or three differently-phrased "
    "specific queries — synonyms for the doctrine, the standard's "
    "operative language, the way courts phrase the rule. Vocabulary "
    "mismatch, not over-specificity, is the usual reason a specific "
    "search misses; searches are cheap and reads are expensive. Broaden "
    "(drop the least essential term, add OR synonyms, use stem* "
    "wildcards) only after rephrasings also miss. If a search returns "
    "many scattered results, narrow it (add an AND term for the "
    "disputed element or the procedural posture) or re-run it with a "
    "larger num_results and triage the deeper list — one deep result "
    "list beats several near-identical queries. Say which way you are "
    "adjusting and why, in one line.\n"
    "6. SELECT: triage before you commit. skim_cluster the promising "
    "result rows (metadata plus editorial syllabus when available; "
    "skims are cheap and draw on their own budget) and use snippets "
    "and skims to cut the field. Then state a shortlist — "
    "'Candidates:' with each case on one line (name, court, year, and a "
    "few words on why it made the list). A skim is never a read: only "
    "read_opinion makes a case citable.\n"
    "7. EVALUATE: abstract_opinion each shortlisted case. The briefing "
    "agent reads the ENTIRE opinion and returns a structured abstract "
    "with verbatim holding language; build your analysis from the "
    "abstracts, quoting only quoted language they contain. Use "
    "read_opinion only when you must study exact language at length "
    "(reconciling conflicting authorities, parsing a controlling "
    "passage). After each abstract, give AT MOST two sentences: the "
    "holding, and whether it helps or hurts here. Run check_treatment "
    "(when available) on every case your answer will rely on. Drop "
    "cases that do not hold up, saying so in a few words.\n"
    "8. ANSWER concisely. No lengthy case summaries: the attorney will "
    "ask for elaboration on specific cases if wanted.\n\n"
    "CITATION CHASING (all protocols): opinions you read cite the "
    "authorities they rely on. When an on-point opinion rests its rule "
    "on earlier cases, run down the one or two most load-bearing "
    "citations (lookup_citation with the reporter citation from the "
    "text, then read_opinion) — the seminal rule case is often one hop "
    "behind the case you found. Chase forward too: find_citing_cases on "
    "a seminal or dated authority surfaces the later cases that applied "
    "it, which is the fastest route to the current controlling "
    "statement of the rule and to how the doctrine has developed since. "
    "Boolean search is only the entry point; the citation network is "
    "where thorough research happens.\n\n"
    "LEARNED VOCABULARY (all protocols): opinions teach you the terms "
    "of art courts actually use — the doctrine's proper name, the "
    "phrase the standard turns on, the statute always cited beside it. "
    "After your first few reads, compare that learned vocabulary "
    "against the queries you have run; if your answer still needs "
    "better authority, re-search with the courts' own language rather "
    "than the wording you started from. Say what new term you are "
    "trying, in one line.\n\n"
    "ADVERSE AUTHORITY (all protocols): before endorsing any position — "
    "ESPECIALLY one the attorney has proposed — run at least one search "
    "framed to find authority AGAINST it: the case opposing counsel "
    "would cite. When your research started from a firm library note "
    "this matters MORE, not less: the note records the firm's own "
    "position, so the adverse search must be independent of it — look "
    "for the authorities the note does NOT mention. Report what the "
    "adverse search surfaced, or say explicitly that it came up empty. "
    "Agreement backed only by supporting searches is advocacy, not "
    "diligence, and the attorney needs diligence.\n\n"
    "Check list_saved_caselaw before searching so prior research is "
    "reused. Prefer the matter's jurisdiction; broaden only when its law "
    "is sparse.\n\n"
    "FIRM LIBRARY (when a FIRM LIBRARY section is present above): those "
    "are the firm's own research outlines and practice guides — the "
    "SURVEY protocol's library pass reads the relevant ones before any "
    "external search. They are internal work product: never cite one as "
    "authority, never attach a [cluster:n] marker to one, and never "
    "repeat a note's statement of the law without verifying its "
    "authorities live — a note's date tells you how stale it may be.\n\n"
)

PROMPT_CONTRACT = (
    "CITATION CONTRACT (mandatory):\n"
    "- Cite ONLY cases you retrieved in this conversation via your tools.\n"
    "- Immediately after each case citation, append its cluster id marker "
    "in the exact form [cluster:12345].\n"
    "- Never cite a case from memory, however confident you are. If your "
    "research surfaces nothing on point, say so plainly instead.\n"
    "- End with an 'Authorities' section listing each cited case with its "
    "citation and a one-line statement of what it establishes.\n\n"
)


def _effort_directive(effort):
    budget = budget_for(effort)
    lines = (
        f"RESEARCH EFFORT: {effort}. You have a budget of "
        f"{budget['max_tool_calls']} substantive tool calls (searches, "
        f"reads, treatment checks) plus {budget['max_skims']} cheap "
        "skims; survey wide with skims, spend the substantive calls "
        "where they matter, and answer once you have solid authority.\n"
    )
    if budget["plan_first"]:
        lines += (
            "High effort: BEFORE any search, output a numbered research plan "
            "(issues, jurisdictions, and the query strategy per issue), "
            "then execute it step by step, adjusting as results come in.\n"
        )
    return lines + "\n"


def prior_research_section(conversation):
    """Structured memory of earlier research turns in this conversation.

    Follow-ups need the cluster ids and queries from previous messages'
    trails — the display text strips [cluster:n] markers, so without this
    the model re-finds cases it already read (the conversation-799
    failure: repeated searches, re-hunting known cases).
    """
    reads = {}
    searches = []
    treatments = {}
    for message in conversation.messages.filter(role="assistant"):
        for event in message.research_trail or []:
            etype = event.get("type")
            if etype == "read" and event.get("cluster_id"):
                reads[event["cluster_id"]] = event
            elif etype in ("search", "citing") and not event.get("repeat"):
                searches.append(event)
            elif etype == "treatment" and event.get("checked"):
                treatments[event.get("cluster_id")] = event

    if not reads and not searches:
        return ""

    lines = [
        "PRIOR RESEARCH IN THIS CONVERSATION (reuse it — do not repeat "
        "these searches; read_opinion works directly on the cluster ids "
        "below):\n"
    ]
    if reads:
        lines.append("Cases already read:\n")
        for cluster_id, event in reads.items():
            treatment = treatments.get(cluster_id)
            note = ""
            if treatment:
                note = (
                    " [NEGATIVE TREATMENT]"
                    if treatment.get("has_negative_treatment")
                    else " [treatment checked: clean]"
                )
            citation = event.get("citation") or ""
            lines.append(
                f"- {event.get('case_name', '?')}"
                f"{', ' + citation if citation else ''}"
                f" (cluster {cluster_id}){note}\n"
            )
    if searches:
        lines.append("Searches already run:\n")
        for event in searches[-25:]:
            lines.append(
                f"- `{event.get('query', '')}` -> {event.get('result_count', 0)} hits\n"
            )
    return "".join(lines) + "\n"


def build_library_section():
    """Listing of the firm's AI-library notes for the research system prompt.

    One line per note (id, folder path, title, summary excerpt) so the
    model can plan read_library_note calls. Sits in the stable prefix
    right after the matter context, so prompt caching still applies
    across tool turns.
    """
    from apps.case.ai.selector import library_folder_path
    from apps.notes.models import get_library_notes

    lines = []
    notes = (
        get_library_notes()
        .select_related(
            "folder",
            "folder__parent",
            "folder__parent__parent",
            "folder__parent__parent__parent",
        )
        .order_by("folder__name", "title")
    )
    for note in notes:
        if not note.content:
            continue
        excerpt = (note.summary or note.content)[:160].replace("\n", " ").strip()
        folder_path = library_folder_path(note.folder)
        updated = note.updated_at.date() if note.updated_at else "unknown"
        lines.append(
            f"- [id {note.id}] {folder_path}: {note.title} "
            f"(updated {updated}): {excerpt}"
        )

    if not lines:
        return ""
    return (
        "FIRM LIBRARY (internal research outlines and practice guides; "
        "read one with read_library_note(note_id) before relying on it):\n"
        + "\n".join(lines)
        + "\n\n"
    )


def build_research_system(context_text, effort, prior_research="", library_section=""):
    """Matter context first (the stable, cacheable prefix), research
    contract after."""
    return (
        context_text
        + "\n\n"
        + library_section
        + PROMPT_ROLE
        + COURTLISTENER_SYNTAX_RULES
        + QUERY_DESIGN_RULES
        + PROMPT_CONTRACT
        + _effort_directive(effort)
        + prior_research
    )


def apply_grounding(response_text, citations_data, trail_events, prior_treated=None):
    """Resolve [cluster:n] markers against the trail, annotate citations.

    Returns (display_text, citations_data, grounding_event). Markers are
    stripped from the display text; each citation entry gains
    ``grounded``/``cluster_id`` when a marker sits just after it in the raw
    text AND that cluster was actually retrieved. Missing or unretrieved
    markers degrade to grounded=False — never an error.

    The grounding event also flags ``untreated_clusters``: cited
    authorities never treatment-checked in this turn or (via
    ``prior_treated``) any earlier turn — the mechanical backstop for the
    prompt's check-everything-you-rely-on rule, which the model has been
    seen skipping (conversation 799 rested on a 1908 case unchecked).
    """
    retrieved = set()
    treated = set(prior_treated or ())
    for event in trail_events:
        if event.get("type") == "read" and event.get("cluster_id"):
            retrieved.add(int(event["cluster_id"]))
        if (
            event.get("type") == "treatment"
            and event.get("checked")
            and event.get("cluster_id")
        ):
            treated.add(int(event["cluster_id"]))
        for row in event.get("results", []) or []:
            if row.get("cluster_id"):
                retrieved.add(int(row["cluster_id"]))

    markers = [
        (m.start(), int(m.group(1))) for m in CLUSTER_MARKER_RE.finditer(response_text)
    ]

    for entry in citations_data:
        if entry.get("citation_type") != "case":
            continue
        entry["grounded"] = False
        entry["cluster_id"] = None
        original = entry.get("original_text") or ""
        pos = response_text.find(original)
        if pos < 0:
            continue
        end = pos + len(original)
        for marker_pos, cluster_id in markers:
            if 0 <= marker_pos - end <= 100:
                entry["cluster_id"] = cluster_id
                entry["grounded"] = cluster_id in retrieved
                break

    cited = sorted({c for _, c in markers})
    grounding_event = {
        "type": "grounding",
        "cited_clusters": cited,
        "ungrounded_clusters": sorted(set(cited) - retrieved),
        "untreated_clusters": sorted(set(cited) - treated),
    }
    display_text = CLUSTER_MARKER_RE.sub("", response_text)
    return display_text, citations_data, grounding_event


def run_research_request(
    conversation,
    matter,
    user,
    user_message,
    llm,
    update_status,
    is_cancelled,
    cache_key,
):
    """Research-kind counterpart of the classic body of process_ai_request.

    Runs inside process_ai_request's try/except, so InterruptedError and
    generic errors get the same handling as classic.
    """
    from .tasks import CLAUDE_MODELS, GEMINI_MODELS, MODEL_HARD_LIMITS, estimate_tokens

    effort = conversation.effort or "medium"
    budget = budget_for(effort)

    update_status("context", "Building context...")
    context_text = assemble_matter_context_with_selection(
        matter,
        user_message=user_message,
        llm=llm,
        user=user,
        conversation=conversation,
    )
    if is_cancelled():
        logger.info("Research request cancelled for conversation %s", conversation.id)
        return

    chat_history = build_chat_history(conversation)

    # Leave generous headroom for tool results, which are resent every
    # model turn: cap the starting prompt at 60% of the model window.
    hard_limit = MODEL_HARD_LIMITS.get(llm, 1_000_000)
    ceiling = int(hard_limit * 0.60)
    while (
        len(chat_history) > 1
        and estimate_tokens(context_text)
        + sum(estimate_tokens(m.get("content", "")) for m in chat_history)
        > ceiling
    ):
        chat_history.pop(0)

    system = build_research_system(
        context_text,
        effort,
        prior_research_section(conversation),
        library_section=build_library_section(),
    )
    tools = build_tools(effort)
    execute_tool = make_executor(
        matter, effort, conversation_id=conversation.id, question=user_message
    )

    # Live research log: concise one-liners accumulated in the status
    # payload so the whole run stays visible in the conversation while it
    # works. IMPORTANT: every status write in this function must go through
    # set_status below — the classic update_status closure writes a fresh
    # payload dict, which would wipe the log out of the cache between
    # tool results (the original "vanishing log" bug: planning-text updates
    # fire per streamed chunk and kept erasing it).
    log_lines = []

    def set_status(status, message):
        current = cache.get(cache_key, {})
        if current.get("status") == "cancelled":
            return
        cache.set(
            cache_key,
            {
                "status": status,
                "message": message,
                "started_at": current.get("started_at", time.time()),
                "activity_log": log_lines[-40:],
            },
            timeout=600,
        )

    def push_log(line, status=None, message=None):
        log_lines.append(line)
        set_status(status or "searching", message or line)

    def on_activity(kind, payload):
        if kind == "tool_call":
            name = payload.get("name", "")
            tool_input = payload.get("input") or {}
            if name == "search_caselaw":
                set_status("searching", f"Searching: `{tool_input.get('query', '')}`")
            elif name == "find_citing_cases":
                set_status(
                    "searching",
                    f"Finding cases citing {tool_input.get('cluster_id', '')}...",
                )
            elif name == "lookup_citation":
                set_status(
                    "searching",
                    f"Looking up citation {tool_input.get('citation', '')}...",
                )
            elif name == "read_opinion":
                set_status(
                    "reading", f"Reading opinion {tool_input.get('cluster_id', '')}..."
                )
            elif name == "skim_cluster":
                set_status("reading", f"Skimming {tool_input.get('cluster_id', '')}...")
            elif name == "check_treatment":
                set_status(
                    "reading",
                    f"Checking treatment of {tool_input.get('cluster_id', '')}...",
                )
            elif name == "read_library_note":
                set_status(
                    "reading",
                    f"Reading library note {tool_input.get('note_id', '')}...",
                )
            else:
                set_status("searching", "Reviewing saved case law...")
        elif kind == "tool_result":
            event = payload
            etype = event.get("type")
            if etype == "search":
                repeat = " — repeat, served from cache" if event.get("repeat") else ""
                overlap = event.get("overlap_count") or 0
                seen = f", {overlap} seen before" if overlap else ""
                push_log(
                    f"Searched `{event.get('query', '')}` "
                    f"({event.get('result_count', 0)} hits{seen}){repeat}"
                )
            elif etype == "citing":
                cited = event.get("case_name") or event.get("cluster_id")
                push_log(f"Found {event.get('result_count', 0)} cases citing *{cited}*")
            elif etype == "read":
                name = event.get("case_name") or event.get("cluster_id")
                part = f" (part {event['part']})" if event.get("part") else ""
                push_log(f"Read *{name}*{part}")
            elif etype == "skim":
                name = event.get("case_name") or event.get("cluster_id")
                detail = "syllabus" if event.get("has_syllabus") else "metadata only"
                push_log(f"Skimmed *{name}* ({detail})")
            elif etype == "abstract":
                name = event.get("case_name") or event.get("cluster_id")
                push_log(f"Read and briefed *{name}*")
            elif etype == "treatment":
                name = event.get("case_name") or event.get("cluster_id")
                verdict = (
                    "negative treatment"
                    if event.get("has_negative_treatment")
                    else "no negative treatment"
                )
                push_log(f"Treatment check *{name}*: {verdict}")
            elif etype == "lookup":
                name = event.get("case_name") or event.get("citation")
                if event.get("found"):
                    push_log(f"Located *{name}* by citation")
                else:
                    push_log(f"Citation {event.get('citation', '')} not found")
            elif etype == "saved":
                push_log(f"Reviewed saved case law ({event.get('count', 0)})")
            elif etype == "library_read":
                title = event.get("title") or event.get("note_id")
                push_log(f"Read library note *{title}*")
        elif kind == "text":
            text = payload.get("text", "")
            if text:
                set_status("planning", text[-300:])

    set_status("planning", "Planning research...")
    time.sleep(0.2)
    if is_cancelled():
        return

    if llm in GEMINI_MODELS:
        response_text, input_tokens, output_tokens, trail = send_to_gemini_with_tools(
            system,
            chat_history,
            tools,
            execute_tool,
            model=GEMINI_MODELS[llm],
            max_tool_calls=budget["max_tool_calls"] + budget["max_skims"],
            is_cancelled=is_cancelled,
            on_activity=on_activity,
        )
    else:
        response_text, input_tokens, output_tokens, trail = send_to_claude_with_tools(
            system,
            chat_history,
            tools,
            execute_tool,
            model=CLAUDE_MODELS.get(llm, "claude-opus-4-8"),
            max_tool_calls=budget["max_tool_calls"] + budget["max_skims"],
            is_cancelled=is_cancelled,
            on_activity=on_activity,
        )

    if is_cancelled():
        return

    set_status("verifying", "Verifying citations...")
    try:
        citations_data = citations_to_dict(verify_all_citations(response_text))
    except Exception:
        logger.exception(
            "Citation verification failed for research conversation %s",
            conversation.id,
        )
        citations_data = []

    prior_treated = set()
    for message in conversation.messages.filter(role="assistant"):
        for event in message.research_trail or []:
            if (
                event.get("type") == "treatment"
                and event.get("checked")
                and event.get("cluster_id")
            ):
                prior_treated.add(int(event["cluster_id"]))

    display_text, citations_data, grounding_event = apply_grounding(
        response_text, citations_data, trail, prior_treated=prior_treated
    )
    trail = trail + [grounding_event]

    if is_cancelled():
        return

    cache.set(
        cache_key,
        {
            "status": "complete",
            "message": "Complete",
            "response": display_text,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "citations": citations_data,
            "research_trail": trail,
            # Kept on the completion payload for debugging; the rendered
            # message shows the persisted trail instead.
            "activity_log": log_lines,
        },
        timeout=600,
    )
