"""The research chat's worker: an agentic CourtListener research loop.

Runs instead of the classic single-completion path when
``conversation.kind == "research"`` (dispatched from process_ai_request;
classic stays byte-identical). The model gets CourtListener tools, a
grounded-citation contract, and a per-depth budget; its searches and
reads stream to the status indicator live, and the full trail lands on
the completion payload for ``Message.research_trail``.
"""

import logging
import re
import time

from django.core.cache import cache

from apps.case.research.query_syntax import COURTLISTENER_SYNTAX_RULES

from .anthropic_client import send_to_claude_with_tools
from .citations import citations_to_dict, verify_all_citations
from .context import assemble_matter_context_with_selection, build_chat_history
from .gemini_client import send_to_gemini_with_tools
from .research_tools import budget_for, build_tools, make_executor

logger = logging.getLogger(__name__)

CLUSTER_MARKER_RE = re.compile(r"\s*\[cluster:(\d+)\]")

PROMPT_ROLE = (
    "RESEARCH MODE. You are a careful legal research associate with live "
    "access to the CourtListener opinion database through tools. Follow "
    "this protocol in order:\n\n"
    "1. STRATEGY (one short paragraph): the legal issue(s), the "
    "controlling jurisdiction, and the doctrinal search terms you will "
    "start from.\n"
    "2. SURVEY: your first searches MUST be doctrinal — the doctrine "
    "name, the legal standard, the operative facts (e.g. a quoted "
    'doctrine phrase like "boundary by agreement" AND acquiescence). '
    "Discover the law from the database. Do NOT open by searching for "
    "case names or citations you already believe exist — your memory is "
    "not a source; searching for a specific case is allowed ONLY after "
    "prior tool results (a search hit, saved case law, or a case cited "
    "inside an opinion you read) have surfaced it.\n"
    "3. ADJUST SCOPE: if a search returns few or off-point results, "
    "widen it (drop the least essential term, add OR synonyms, use "
    "stem* wildcards). If it returns many scattered results, narrow it "
    "(add an AND term for the disputed element or the procedural "
    "posture). Say which way you are adjusting and why, in one line.\n"
    "4. SELECT: once results look on point, state a shortlist — "
    "'Candidates:' with each case on one line (name, court, year, and a "
    "few words on why it made the list).\n"
    "5. EVALUATE: read_opinion each shortlisted case. After each read, "
    "give AT MOST two sentences: the holding, and whether it helps or "
    "hurts here. Run check_treatment (when available) on every case "
    "your answer will rely on. Drop cases that do not hold up, saying "
    "so in a few words.\n"
    "6. ANSWER concisely. No lengthy case summaries: the attorney will "
    "ask for elaboration on specific cases if wanted.\n\n"
    "Check list_saved_caselaw before searching so prior research is "
    "reused. Prefer the matter's jurisdiction; broaden only when its law "
    "is sparse.\n\n"
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


def _depth_directive(depth):
    budget = budget_for(depth)
    lines = (
        f"RESEARCH DEPTH: {depth}. You have a budget of "
        f"{budget['max_tool_calls']} tool calls; spend them where they "
        "matter and answer once you have solid authority.\n"
    )
    if budget["plan_first"]:
        lines += (
            "Deep mode: BEFORE any search, output a numbered research plan "
            "(issues, jurisdictions, and the query strategy per issue), "
            "then execute it step by step, adjusting as results come in.\n"
        )
    return lines + "\n"


def build_research_system(context_text, depth):
    """Matter context first (the stable, cacheable prefix), research
    contract after."""
    return (
        context_text
        + "\n\n"
        + PROMPT_ROLE
        + COURTLISTENER_SYNTAX_RULES
        + PROMPT_CONTRACT
        + _depth_directive(depth)
    )


def apply_grounding(response_text, citations_data, trail_events):
    """Resolve [cluster:n] markers against the trail, annotate citations.

    Returns (display_text, citations_data, grounding_event). Markers are
    stripped from the display text; each citation entry gains
    ``grounded``/``cluster_id`` when a marker sits just after it in the raw
    text AND that cluster was actually retrieved. Missing or unretrieved
    markers degrade to grounded=False — never an error.
    """
    retrieved = set()
    for event in trail_events:
        if event.get("type") == "read" and event.get("cluster_id"):
            retrieved.add(int(event["cluster_id"]))
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

    depth = conversation.research_depth or "standard"
    budget = budget_for(depth)

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

    system = build_research_system(context_text, depth)
    tools = build_tools(depth)
    execute_tool = make_executor(matter, depth)

    # Live research log: concise one-liners accumulated in the status
    # payload so the whole run stays visible in the conversation while it
    # works (the one-line status alone loses history between polls). The
    # persisted trail takes over once the answer lands.
    log_lines = []

    def push_log(line):
        log_lines.append(line)
        current = cache.get(cache_key, {})
        if current.get("status") not in ("cancelled", None):
            current["research_log"] = log_lines[-40:]
            cache.set(cache_key, current, timeout=600)

    def on_activity(kind, payload):
        if kind == "tool_call":
            name = payload.get("name", "")
            tool_input = payload.get("input") or {}
            if name == "search_caselaw":
                update_status(
                    "searching", f"Searching: `{tool_input.get('query', '')}`"
                )
            elif name == "read_opinion":
                update_status(
                    "reading", f"Reading opinion {tool_input.get('cluster_id', '')}..."
                )
            elif name == "check_treatment":
                update_status(
                    "reading",
                    f"Checking treatment of {tool_input.get('cluster_id', '')}...",
                )
            else:
                update_status("searching", "Reviewing saved case law...")
        elif kind == "tool_result":
            event = payload
            etype = event.get("type")
            if etype == "search":
                push_log(
                    f"Searched `{event.get('query', '')}` "
                    f"({event.get('result_count', 0)} hits)"
                )
            elif etype == "read":
                name = event.get("case_name") or event.get("cluster_id")
                push_log(f"Read *{name}*")
            elif etype == "treatment":
                name = event.get("case_name") or event.get("cluster_id")
                verdict = (
                    "negative treatment"
                    if event.get("has_negative_treatment")
                    else "no negative treatment"
                )
                push_log(f"Treatment check *{name}*: {verdict}")
            elif etype == "saved":
                push_log(f"Reviewed saved case law ({event.get('count', 0)})")
        elif kind == "text":
            text = payload.get("text", "")
            if text:
                update_status("planning", text[-300:])

    update_status("planning", "Planning research...")
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
            max_tool_calls=budget["max_tool_calls"],
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
            max_tool_calls=budget["max_tool_calls"],
            is_cancelled=is_cancelled,
            on_activity=on_activity,
        )

    if is_cancelled():
        return

    update_status("verifying", "Verifying citations...")
    try:
        citations_data = citations_to_dict(verify_all_citations(response_text))
    except Exception:
        logger.exception(
            "Citation verification failed for research conversation %s",
            conversation.id,
        )
        citations_data = []

    display_text, citations_data, grounding_event = apply_grounding(
        response_text, citations_data, trail
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
            "research_log": log_lines,
        },
        timeout=600,
    )
