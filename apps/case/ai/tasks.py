"""
Background tasks for AI chat processing.
"""

import logging
import time

from .anthropic_client import send_to_claude
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

        # The AI can record timeline facts and witnesses when directed;
        # the fenced blocks it emits are applied after the response arrives.
        # SOURCE_LINKING (inline source links for prose) always rides
        # along, but each write protocol is included only when the recent
        # user messages actually point at timeline or witness work, so
        # unrelated conversations carry no standing write instructions.
        from .context import SOURCE_LINKING
        from .fact_blocks import (
            FACT_BLOCK_RE,
            FACTS_PROTOCOL,
            FACTS_TRIGGER_RE,
            apply_fact_blocks,
        )
        from .note_blocks import (
            NOTE_BLOCKS_RE,
            NOTES_PROTOCOL,
            NOTES_TRIGGER_RE,
            apply_note_blocks,
            strip_fake_note_confirmations,
        )
        from .witness_blocks import (
            WITNESS_BLOCK_RE,
            WITNESS_TRIGGER_RE,
            WITNESSES_PROTOCOL,
            apply_witness_blocks,
        )

        context_text += "\n\n" + SOURCE_LINKING

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
        armed_protocols = []
        if FACTS_TRIGGER_RE.search(recent_user_text):
            context_text += "\n\n" + FACTS_PROTOCOL
            armed_protocols.append("facts")
        if WITNESS_TRIGGER_RE.search(recent_user_text):
            context_text += "\n\n" + WITNESSES_PROTOCOL
            armed_protocols.append("witnesses")
        if NOTES_TRIGGER_RE.search(recent_user_text):
            context_text += "\n\n" + NOTES_PROTOCOL
            armed_protocols.append("notes")
        if armed_protocols:
            log_activity("Write protocols included: " + ", ".join(armed_protocols))

        if is_cancelled():
            logger.info("AI request cancelled for conversation %s", conversation_id)
            return

        # Timestamped history, with user names when multiple people chat
        chat_history = build_chat_history(conversation)

        # Final size guard. estimate_tokens (chars/4) under-counts real
        # tokenization, so apply the cap at 80% of the model window and
        # treat the estimate generously. If the assembled prompt plus the
        # chat history would still exceed the cap, drop the oldest chat
        # messages until it fits — preserving the current user message and
        # the most recent exchanges. Better than a 400 from the provider.
        hard_limit = MODEL_HARD_LIMITS.get(llm, 1_000_000)
        send_ceiling = int(hard_limit * 0.80)
        context_tokens = estimate_tokens(context_text)

        def _history_tokens(history):
            return sum(estimate_tokens(m.get("content", "")) for m in history)

        history_tokens = _history_tokens(chat_history)
        if context_tokens + history_tokens > send_ceiling:
            dropped = 0
            # Trim from the front (oldest) while keeping at least the most
            # recent message (the one we're responding to).
            while (
                len(chat_history) > 1
                and context_tokens + _history_tokens(chat_history) > send_ceiling
            ):
                chat_history.pop(0)
                dropped += 1
            history_tokens = _history_tokens(chat_history)
            log_activity(
                f"Trimmed {dropped} oldest chat messages to fit the model window"
            )
            logger.warning(
                "AI prompt over send ceiling for %s (~%d tokens > %d). "
                "Dropped %d oldest chat messages; final estimate ~%d tokens.",
                llm,
                context_tokens + history_tokens + dropped,  # rough pre-trim figure
                send_ceiling,
                dropped,
                context_tokens + history_tokens,
            )
            if context_tokens + history_tokens > send_ceiling:
                logger.error(
                    "AI prompt still over send ceiling after trimming chat "
                    "history for conversation %s (context alone ~%d tokens > %d). "
                    "Request will likely be rejected by the provider.",
                    conversation_id,
                    context_tokens,
                    send_ceiling,
                )

        log_activity(
            f"History: {len(chat_history)} messages; "
            f"sending ~{context_tokens + history_tokens:,} tokens total"
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
        from .handles import HANDLE_RE, resolve_handles_for_chat

        if HANDLE_RE.search(response_text):
            response_text = resolve_handles_for_chat(response_text, matter)

        # Verify citations in the response
        update_status("verifying", "Verifying citations...")
        log_activity("Checking citations against CourtListener...")
        logger.info(
            "Starting citation verification for conversation %s", conversation_id
        )
        try:
            verified_citations = verify_all_citations(response_text)
            citations_data = citations_to_dict(verified_citations)
            if citations_data:
                log_activity(f"{len(citations_data)} citations checked")
            else:
                log_activity("No case citations to check")
            logger.info(
                "Citation verification complete for conversation %s: %d citations found",
                conversation_id,
                len(citations_data),
            )
        except Exception as e:
            logger.exception(
                "Citation verification failed for conversation %s: %s",
                conversation_id,
                e,
            )
            citations_data = []
            log_activity("Citation check failed; skipped")

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
