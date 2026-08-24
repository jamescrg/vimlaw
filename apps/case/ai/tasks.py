"""
Background tasks for AI chat processing.
"""

import logging
import time

from .anthropic_client import count_claude_tokens, send_to_claude
from .citations import citations_to_dict, verify_all_citations
from .gemini_client import send_to_gemini, send_to_gemini_streaming
from .selector import MODEL_HARD_LIMITS, estimate_tokens
from .status import FINAL_TTL, RUNNING_TTL, RunHeartbeat, status_cache

logger = logging.getLogger(__name__)

# Picker choice -> Anthropic model ID. Every entry has a 1M-token context
# window with no beta header and no long-context surcharge; the selector
# budget plus the hard-ceiling check in context assembly keep prompts inside
# it. "claude" is the retired Sonnet 4.6 choice, kept so conversations
# started on it still send.
CLAUDE_MODELS = {
    "claude": "claude-sonnet-4-6",
    "claude-opus-5": "claude-opus-5",
    "claude-fable": "claude-fable-5",
    "claude-opus": "claude-opus-4-8",
    "claude-opus-4-6": "claude-opus-4-6",
}

# Model ID used when a conversation carries a picker key that is in neither
# dispatch table (e.g. a key retired without a mapping). Not a default: new
# conversations get their default from the surface that creates them.
CLAUDE_FALLBACK_MODEL = "claude-sonnet-4-6"

# Picker choice -> Gemini model ID. "gemini-pro" is the retired 2.5 Pro pin.
GEMINI_MODELS = {
    "gemini-flash": "gemini-2.5-flash",
    "gemini-pro": "gemini-2.5-pro",
    "gemini-pro-latest": "gemini-pro-latest",
}


class PromptTooLargeError(Exception):
    """The assembled prompt cannot fit the model's context window."""


# Estimates at or above this share of the window get an exact count before
# the Claude send; below it the conservative estimate is trusted and the
# extra round trip (which re-uploads the whole prompt) is skipped.
EXACT_COUNT_THRESHOLD = 0.5
# Estimate-based send ceiling, as a share of the model window.
ESTIMATE_CEILING = 0.80
# Exact-count send ceiling; the remainder is headroom for the turn itself.
EXACT_CEILING = 0.98


def _trim_history(chat_history, context_tokens, ceiling):
    """Drop the oldest messages until the estimate fits; keep the newest."""
    dropped = 0

    def total():
        return context_tokens + sum(
            estimate_tokens(m.get("content", "")) for m in chat_history
        )

    while len(chat_history) > 1 and total() > ceiling:
        chat_history.pop(0)
        dropped += 1
    return dropped, total()


def fit_prompt_to_window(
    context_text, chat_history, llm, log_activity, ceiling_share=ESTIMATE_CEILING
):
    """Make the prompt fit the model window, trimming chat history as needed.

    Returns (chat_history, prompt_tokens). Trims against the conservative
    estimate first; for Claude, when the estimate is within striking
    distance of the window, asks the API for the exact count (the model's
    own tokenizer) and trims again against that. Raises
    PromptTooLargeError when the context alone cannot fit, with a message
    meant for the chat. ``ceiling_share`` is the share of the window the
    estimate may fill; the agent loop passes a lower one to leave room
    for the tool results it appends during the turn.
    """
    hard_limit = MODEL_HARD_LIMITS.get(llm, 1_000_000)
    context_tokens = estimate_tokens(context_text)
    estimate_ceiling = int(hard_limit * ceiling_share)

    dropped, prompt_tokens = _trim_history(
        chat_history, context_tokens, estimate_ceiling
    )
    if dropped:
        log_activity(f"Trimmed {dropped} oldest chat messages to fit the model window")
        logger.warning(
            "AI prompt over send ceiling for %s (%d); dropped %d oldest chat "
            "messages, estimate now ~%d tokens.",
            llm,
            estimate_ceiling,
            dropped,
            prompt_tokens,
        )

    if llm in GEMINI_MODELS:
        # No exact counter wired for Gemini; its tokenizer is also less
        # dense than the estimate assumes, so an over-ceiling estimate here
        # is logged and sent rather than refused.
        if prompt_tokens > estimate_ceiling:
            logger.error(
                "AI prompt still over send ceiling for %s after trimming "
                "(context alone ~%d tokens > %d); sending anyway.",
                llm,
                context_tokens,
                estimate_ceiling,
            )
        return chat_history, prompt_tokens

    if prompt_tokens < hard_limit * EXACT_COUNT_THRESHOLD:
        return chat_history, prompt_tokens

    model = CLAUDE_MODELS.get(llm, CLAUDE_FALLBACK_MODEL)
    exact_ceiling = int(hard_limit * EXACT_CEILING)
    exact = count_claude_tokens(context_text, chat_history, model)
    if exact is None:
        # Count unavailable; the estimate already passed the 80% ceiling.
        return chat_history, prompt_tokens
    log_activity(f"Exact prompt size: {exact:,} tokens")

    # The exact count and the estimate disagree by some ratio; trim history
    # against an estimate ceiling scaled by that ratio, then re-count. A
    # couple of rounds converge; the loop is bounded regardless.
    for _ in range(3):
        if exact <= exact_ceiling:
            return chat_history, exact
        if len(chat_history) <= 1:
            break
        ratio = exact / max(prompt_tokens, 1)
        scaled_ceiling = int(exact_ceiling / ratio)
        dropped, prompt_tokens = _trim_history(
            chat_history, context_tokens, scaled_ceiling
        )
        if not dropped:
            break
        log_activity(f"Trimmed {dropped} oldest chat messages to fit the model window")
        recount = count_claude_tokens(context_text, chat_history, model)
        if recount is None:
            return chat_history, prompt_tokens
        exact = recount
    if exact <= exact_ceiling:
        return chat_history, exact
    logger.error(
        "AI prompt cannot fit %s window: %d exact tokens > %d with %d history "
        "messages.",
        model,
        exact,
        exact_ceiling,
        len(chat_history),
    )
    raise PromptTooLargeError(_too_large_message(exact, hard_limit))


def _too_large_message(tokens, hard_limit):
    return (
        f"The case file is too large for this model (about {tokens:,} tokens "
        f"against a {hard_limit:,} limit). Lower the AI context setting on "
        "some always-included documents, case law or notes, or start a new "
        "conversation."
    )


def armed_write_protocols(conversation, user_message):
    """The write protocols the recent user messages call for.

    The AI can record timeline facts, witnesses and notes when directed;
    the fenced blocks it emits are applied after the response arrives.
    Each protocol is included only when the recent user messages actually
    point at that kind of work, so unrelated conversations carry no
    standing write instructions. Returns (protocol_text, names) where
    protocol_text is ready to append to the system context ("" when
    nothing is armed). Shared by the classic and agent turns.
    """
    from .fact_blocks import FACTS_PROTOCOL, FACTS_TRIGGER_RE
    from .note_blocks import NOTES_PROTOCOL, NOTES_TRIGGER_RE
    from .witness_blocks import WITNESS_TRIGGER_RE, WITNESSES_PROTOCOL

    # Current message plus a few before it, so follow-up directives
    # ("also add the crash date") keep the protocol from a turn or
    # two after the one that named the timeline.
    recent_user_text = "\n".join(
        [user_message]
        + list(
            conversation.messages.filter(role="user")
            .order_by("-created_at")
            .values_list("content", flat=True)[:4]
        )
    )
    text = ""
    names = []
    if FACTS_TRIGGER_RE.search(recent_user_text):
        text += "\n\n" + FACTS_PROTOCOL
        names.append("facts")
    if WITNESS_TRIGGER_RE.search(recent_user_text):
        text += "\n\n" + WITNESSES_PROTOCOL
        names.append("witnesses")
    if NOTES_TRIGGER_RE.search(recent_user_text):
        text += "\n\n" + NOTES_PROTOCOL
        names.append("notes")
    return text, names


def finalize_response(
    response_text, matter, user, conversation, draft_link, update_status, log_activity
):
    """Post-process a model reply before it is stored.

    Applies draft edits and the fenced write blocks (each replaced by
    confirmation lines), resolves leaked source handles into links, then
    verifies case citations. Returns (response_text, citations_data).
    Shared by the classic and agent turns so both modes write through
    exactly one path.
    """
    from .fact_blocks import FACT_BLOCK_RE, apply_fact_blocks
    from .handles import HANDLE_RE, resolve_handles_for_chat
    from .note_blocks import (
        NOTE_BLOCKS_RE,
        apply_note_blocks,
        strip_fake_note_confirmations,
    )
    from .witness_blocks import WITNESS_BLOCK_RE, apply_witness_blocks

    # Apply draft edits before citation verification, so the stored
    # message carries the outcome text instead of the raw block.
    if draft_link:
        from apps.drafts import chat as drafts_chat

        if drafts_chat.DRAFT_EDITS_RE.search(response_text):
            update_status("applying", "Applying edits to the draft...")
            response_text = drafts_chat.apply_edit_blocks(response_text, draft_link)
            log_activity("Draft edits applied")

    # Create any facts and witnesses the AI was directed to record,
    # replacing each block with confirmation lines before the message
    # is stored.
    if FACT_BLOCK_RE.search(response_text):
        update_status("applying", "Adding facts to the timeline...")
        response_text = apply_fact_blocks(response_text, matter, user)
        log_activity("Facts recorded on the timeline")
    if WITNESS_BLOCK_RE.search(response_text):
        update_status("applying", "Adding witnesses...")
        response_text = apply_witness_blocks(response_text, matter, user)
        log_activity("Witnesses recorded")
    # Order matters: imitation confirmations are scrubbed from the raw
    # response first (only model-written lines can match at this
    # point), then real blocks are applied and produce the genuine
    # confirmation lines.
    response_text = strip_fake_note_confirmations(response_text)
    if NOTE_BLOCKS_RE.search(response_text):
        update_status("applying", "Writing notes...")
        response_text = apply_note_blocks(response_text, matter, user)
        log_activity("Notes written")

    # Any raw [doc:]/[hl:]/[note:] handles the model leaked into prose
    # become human-readable markdown links (hallucinated ids are
    # omitted). Runs after the write blocks so their content has
    # already been consumed.
    if HANDLE_RE.search(response_text):
        response_text = resolve_handles_for_chat(response_text, matter)

    # Verify citations in the response
    update_status("verifying", "Verifying citations...")
    log_activity("Checking citations against CourtListener...")
    logger.info("Starting citation verification for conversation %s", conversation.id)
    try:
        verified_citations = verify_all_citations(response_text)
        citations_data = citations_to_dict(verified_citations)
        if citations_data:
            log_activity(f"{len(citations_data)} citations checked")
        else:
            log_activity("No case citations to check")
        logger.info(
            "Citation verification complete for conversation %s: %d citations found",
            conversation.id,
            len(citations_data),
        )
    except Exception as e:
        logger.exception(
            "Citation verification failed for conversation %s: %s",
            conversation.id,
            e,
        )
        citations_data = []
        log_activity("Citation check failed; skipped")
    return response_text, citations_data


def process_ai_request(
    conversation_id: int,
    matter_id: int,
    user_message: str,
    user_id: int,
    llm: str,
):
    """
    Process AI request in background thread, updating status along the way.

    Assembles context (including intelligent selection for large matters),
    builds chat history, then sends to the AI model.

    Args:
        conversation_id: ID of the conversation being processed
        matter_id: ID of the matter for context assembly
        user_message: The user's question (used by intelligent selector)
        user_id: ID of the requesting user
        llm: The LLM to use (claude, gemini-flash, gemini-pro)
    """
    from django.contrib.auth import get_user_model

    from apps.matters.models import Matter

    from .context import assemble_matter_context_with_selection, build_chat_history
    from .models import Conversation

    # Agentic conversations take the tool-loop turn instead; everything
    # around it (thread, status key, poller, cancellation) is shared.
    kind = (
        Conversation.objects.filter(id=conversation_id)
        .values_list("kind", flat=True)
        .first()
    )
    if kind == "agent":
        from . import agent

        return agent.run_agent_request(
            conversation_id, matter_id, user_message, user_id, llm
        )

    cache_key = f"ai_status_{conversation_id}"
    started_at = time.time()

    # Live activity log: durable one-liners describing each stage of the
    # turn (context assembly, material selection, the model call, block
    # application, cite checking), rendered under the status line by the
    # 1s poll. Every status write carries the log so transient status
    # updates never blank it.
    activity_log: list[str] = []
    last_status = ["starting", "Starting..."]

    def update_status(status: str, message: str):
        """Update the cache with current status, unless cancelled."""
        current = status_cache.get(cache_key, {})
        if current.get("status") == "cancelled":
            return
        last_status[:] = [status, message]
        payload = {
            "status": status,
            "message": message,
            "started_at": started_at,
        }
        if activity_log:
            payload["activity_log"] = activity_log[-40:]
        status_cache.set(cache_key, payload, timeout=RUNNING_TTL)

    def log_activity(line: str):
        """Append a line to the live log and refresh the status payload."""
        activity_log.append(line)
        update_status(*last_status)

    def is_cancelled():
        """Check if the request has been cancelled."""
        status_data = status_cache.get(cache_key, {})
        return status_data.get("status") == "cancelled"

    heartbeat = RunHeartbeat(conversation_id).start()
    try:
        # Assemble context (may call Gemini Flash for intelligent selection)
        update_status("context", "Building context...")

        User = get_user_model()
        matter = Matter.objects.get(id=matter_id)
        user = User.objects.get(id=user_id)
        conversation = Conversation.objects.get(id=conversation_id)

        context_text = assemble_matter_context_with_selection(
            matter,
            user_message=user_message,
            llm=llm,
            user=user,
            conversation=conversation,
            on_activity=log_activity,
        )

        # A linked draft appends its text and the edit protocol; the AI can
        # then propose tracked changes applied via the LibreOffice companion.
        draft_link = getattr(conversation, "draft_link", None)
        if draft_link:
            from apps.drafts import chat as drafts_chat

            context_text += drafts_chat.build_draft_section(draft_link)
            log_activity(f"Linked draft loaded: {draft_link.name}")

        # SOURCE_LINKING (inline source links for prose) always rides
        # along; the write protocols only when the recent user messages
        # call for them (see armed_write_protocols).
        from .context import SOURCE_LINKING

        context_text += "\n\n" + SOURCE_LINKING
        protocol_text, armed_protocols = armed_write_protocols(
            conversation, user_message
        )
        context_text += protocol_text
        if armed_protocols:
            log_activity("Write protocols included: " + ", ".join(armed_protocols))

        if is_cancelled():
            logger.info("AI request cancelled for conversation %s", conversation_id)
            return

        # Timestamped history, with user names when multiple people chat
        chat_history = build_chat_history(conversation)

        # Final size guard: trim the oldest chat messages (never the current
        # one) until the prompt fits, then for Claude verify large prompts
        # with an exact count. Raises PromptTooLargeError instead of
        # sending a request the provider will reject.
        chat_history, prompt_tokens = fit_prompt_to_window(
            context_text, chat_history, llm, log_activity
        )

        log_activity(
            f"History: {len(chat_history)} messages; "
            f"sending ~{prompt_tokens:,} tokens total"
        )

        # Set connecting status
        update_status("connecting", "Connecting to AI...")

        # Brief pause to show connecting status
        time.sleep(0.3)

        # Check for cancellation before making AI call
        if is_cancelled():
            logger.info("AI request cancelled for conversation %s", conversation_id)
            return

        if llm in GEMINI_MODELS:
            # Use streaming with thought summaries for Gemini
            model = GEMINI_MODELS[llm]

            log_activity(f"Request submitted to {model}")
            update_status("thinking", "Thinking...")

            def on_thought(thought_text: str):
                """Callback for thought summaries from Gemini."""
                # Truncate very long thoughts for display
                display_text = thought_text[:300]
                if len(thought_text) > 300:
                    display_text += "..."
                update_status("thinking", display_text)

            response_text, input_tokens, output_tokens = send_to_gemini_streaming(
                context_text,
                chat_history,
                model=model,
                on_thought=on_thought,
                is_cancelled=is_cancelled,
                conversation_id=conversation_id,
            )
        else:
            # Claude - show elapsed time updates
            update_status("generating", "Generating response...")

            claude_model = CLAUDE_MODELS.get(llm, CLAUDE_FALLBACK_MODEL)
            log_activity(f"Request submitted to {claude_model}")

            response_text, input_tokens, output_tokens = send_to_claude(
                context_text,
                chat_history,
                model=claude_model,
                is_cancelled=is_cancelled,
            )

        # Check for cancellation before citation verification
        if is_cancelled():
            logger.info("AI request cancelled for conversation %s", conversation_id)
            return

        log_activity(
            f"Response received (~{output_tokens:,} tokens, "
            f"{int(time.time() - started_at)}s)"
        )

        # Write blocks, handle links and the citation check, shared with
        # the agent turn.
        response_text, citations_data = finalize_response(
            response_text,
            matter,
            user,
            conversation,
            draft_link,
            update_status,
            log_activity,
        )

        # Set complete status with response data (unless cancelled)
        if is_cancelled():
            logger.info("AI request cancelled for conversation %s", conversation_id)
            return

        logger.info(
            "Storing %d citations in cache for conversation %s",
            len(citations_data),
            conversation_id,
        )
        status_cache.set(
            cache_key,
            {
                "status": "complete",
                "message": "Complete",
                "response": response_text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "citations": citations_data,
                # Kept on the completion payload for debugging, like the
                # research log; the rendered message replaces the live view.
                "activity_log": activity_log,
            },
            timeout=FINAL_TTL,
        )

    except InterruptedError:
        # Request was cancelled - just log and exit quietly
        logger.info("AI request cancelled for conversation %s", conversation_id)

    except Exception as e:
        logger.exception(
            "Error in background AI request for conversation %s", conversation_id
        )
        # Don't overwrite if already cancelled
        current = status_cache.get(cache_key, {})
        if current.get("status") != "cancelled":
            status_cache.set(
                cache_key,
                {
                    "status": "error",
                    "message": f"Error: {str(e)}",
                    # How far the turn got before failing.
                    "activity_log": activity_log,
                },
                timeout=FINAL_TTL,
            )
    finally:
        heartbeat.stop()


# ── Conversation Summary ─────────────────────────────────────────────────────

CONVERSATION_SUMMARY_PROMPT = (
    "You are a legal conversation summarizer. Produce a concise ~100-word summary "
    "of this AI conversation. Focus on: what legal questions were asked, what "
    "advice or analysis was provided, key conclusions reached, and any specific "
    "documents or case law discussed. Be specific and factual."
)

CONVERSATION_TEXT_LIMIT = 15_000


def generate_conversation_summary(conversation_id):
    """Generate an AI summary of a conversation using Gemini Flash.

    Called after each AI response and as a backfill task.
    Always overwrites existing summary (conversations grow over time).
    """
    from .models import Conversation

    try:
        conversation = Conversation.objects.get(id=conversation_id)
    except Conversation.DoesNotExist:
        logger.error(f"Conversation {conversation_id} not found for summary")
        return

    messages = conversation.messages.select_related("user").order_by("created_at")
    if not messages.exists():
        return

    # Format messages into text
    lines = []
    for msg in messages:
        if msg.role == "user":
            name = msg.user.get_full_name() if msg.user else "User"
            lines.append(f"[User - {name}]: {msg.content}")
        else:
            lines.append(f"[Assistant]: {msg.content}")

    text = "\n\n".join(lines)
    if len(text) > CONVERSATION_TEXT_LIMIT:
        text = text[:CONVERSATION_TEXT_LIMIT] + "\n... (conversation continues)"

    try:
        response_text, _, _ = send_to_gemini(
            system_context=CONVERSATION_SUMMARY_PROMPT,
            messages=[{"role": "user", "content": text}],
            model="gemini-2.5-flash",
        )

        conversation.summary = response_text.strip()
        conversation.save(update_fields=["summary"])

        logger.info(
            f"Summary generated for conversation {conversation_id}: "
            f"{len(conversation.summary)} chars"
        )

    except Exception as e:
        logger.warning(
            f"Summary generation failed for conversation {conversation_id}: {e}"
        )
