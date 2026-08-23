"""
Anthropic Claude API client for AI chat.

Uses streaming to support cancellation mid-request, and marks the system
prompt as cacheable so repeat messages in the same conversation benefit
from Anthropic's prompt-cache pricing (~10% of input cost on cache hits).
The tool loop additionally rolls a cache breakpoint through the message
history, so accumulated tool results are read from cache on each turn
instead of being re-billed at full input price.
"""

import logging
import time
from typing import Callable

import anthropic
from django.conf import settings

from .agent_types import (
    FORCED_ANSWER_NOTE,
    LoopResult,
    TurnUsage,
    batch_is_all_budget_errors,
)

logger = logging.getLogger(__name__)


# Anthropic's prompt cache has a per-model minimum prefix: 1024 tokens on
# Sonnet 4.6 and Opus 4.8, 4096 on Opus 4.6. We use a character heuristic
# (~4 chars/token) that clears the 1024 minimum and avoids marking small
# system prompts; below it we fall back to the plain string form. On Opus
# 4.6 a marked prompt under ~16k chars simply doesn't cache — the marker is
# ignored, not billed — so matter contexts that small show no cache lines in
# the log. Every real matter context clears it comfortably.
_ANTHROPIC_CACHE_MIN_CHARS = 5000


def _build_system(system_context):
    """Return the `system=` argument for messages.stream.

    For large prompts, returns a content block list with an ephemeral
    cache_control marker so Anthropic caches the prefix for ~5 minutes and
    subsequent identical prefixes pay ~10% of the input rate. For smaller
    prompts, returns the plain string (no caching — the cache-write premium
    isn't justified below the minimum cacheable length).

    A list of segments (the agent turn's stable orientation followed by
    its per-turn tail) becomes one text block per segment, each marked
    when it is large enough, so the stable prefix keeps hitting the cache
    while the tail changes.
    """
    if isinstance(system_context, (list, tuple)):
        blocks = []
        for segment in system_context:
            if not segment:
                continue
            block = {"type": "text", "text": segment}
            if len(segment) >= _ANTHROPIC_CACHE_MIN_CHARS:
                block["cache_control"] = {"type": "ephemeral"}
            blocks.append(block)
        return blocks
    if system_context and len(system_context) >= _ANTHROPIC_CACHE_MIN_CHARS:
        return [
            {
                "type": "text",
                "text": system_context,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    return system_context


def _roll_message_cache_marker(convo: list[dict]) -> None:
    """Move the rolling cache breakpoint to the conversation's last block.

    The tool loop resends the whole conversation — including every
    accumulated tool result — on every model turn, and without a breakpoint
    in the messages Anthropic bills all of it at full input price each time
    (the system-prompt marker only covers the prefix up to the system
    block). Marking the newest block caches everything before it, so the
    next turn reads the prior turns at ~10% of the input rate and pays full
    price only for what was just appended.

    One marker rolls forward each turn (older ones are stripped so the
    4-breakpoint request limit is never hit); the cache lookup still finds
    the previous turn's entry by walking back from the new marker. Plain
    string content (the initial chat history) is left unmarked — the system
    marker already covers the prefix on the first turn.
    """
    for msg in convo:
        if isinstance(msg["content"], list):
            for block in msg["content"]:
                if isinstance(block, dict):
                    block.pop("cache_control", None)
    last_content = convo[-1]["content"]
    if isinstance(last_content, list) and last_content:
        last_block = last_content[-1]
        if isinstance(last_block, dict):
            last_block["cache_control"] = {"type": "ephemeral"}


def _format_messages(messages: list[dict]) -> list[dict]:
    """Reduce chat-history dicts to the role/content shape the API takes."""
    return [{"role": msg["role"], "content": msg["content"]} for msg in messages]


def count_claude_tokens(
    system_context: str,
    messages: list[dict],
    model: str,
) -> int | None:
    """Exact prompt token count for the request send_to_claude would make.

    Uses the Messages count_tokens endpoint, which runs the target model's
    own tokenizer and is free of charge. The send-site size guard relies on
    it because the chars-per-token heuristic in selector.estimate_tokens
    under-counts dense legal material (OCR'd filings, citations, tables)
    and the Opus 4.7+ tokenizer is denser still; a chat once cleared the
    heuristic's 80%-of-window ceiling and was still rejected at 1.14M
    tokens.

    Returns None when the count cannot be obtained (no key, network, a
    model the endpoint rejects) so callers fall back to the estimate
    rather than failing the chat.
    """
    try:
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        result = client.messages.count_tokens(
            model=model,
            system=_build_system(system_context),
            messages=_format_messages(messages),
        )
    except Exception as exc:
        logger.warning(
            "Claude token count unavailable for %s (%s); using estimate", model, exc
        )
        return None
    return result.input_tokens


def send_to_claude(
    system_context: str,
    messages: list[dict],
    model: str = "claude-sonnet-4-6",
    is_cancelled: Callable[[], bool] | None = None,
) -> tuple[str, int, int]:
    """
    Send a conversation to Claude and get a response using streaming.

    Uses streaming mode to allow cancellation mid-request. When cancelled,
    only tokens generated up to that point are billed.

    Sonnet 4.6, Opus 4.6 and Opus 4.8 all expose a 1M-token context window on
    this account without any beta header and at standard input pricing. The
    selector's MODEL_CONTEXT_LIMITS is a soft cap on auto-selected content;
    the assembler enforces a separate hard ceiling so the total prompt stays
    under the model window even when always-included content (highlights,
    facts, notes, reference convos) inflates the fixed portion.

    Args:
        system_context: The system prompt with matter context
        messages: List of {"role": "user"|"assistant", "content": str}
        model: Claude model to use — see CLAUDE_MODELS in tasks.py
        is_cancelled: Optional callback that returns True if request should be cancelled

    Returns:
        tuple of (response_text, input_tokens, output_tokens)

    Raises:
        anthropic.APIError: If the API call fails
        InterruptedError: If the request was cancelled
    """
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    formatted_messages = _format_messages(messages)

    # Use streaming to allow cancellation
    response_parts = []
    input_tokens = 0
    output_tokens = 0

    with client.messages.stream(
        model=model,
        max_tokens=4096,
        system=_build_system(system_context),
        messages=formatted_messages,
    ) as stream:
        for text in stream.text_stream:
            # Check for cancellation on each chunk
            if is_cancelled and is_cancelled():
                raise InterruptedError("Request cancelled")
            response_parts.append(text)

        # Get final usage stats
        final_message = stream.get_final_message()
        input_tokens = final_message.usage.input_tokens
        output_tokens = final_message.usage.output_tokens

        # Log prompt-cache usage when available so we can see hit rate in logs.
        cache_created = (
            getattr(final_message.usage, "cache_creation_input_tokens", 0) or 0
        )
        cache_read = getattr(final_message.usage, "cache_read_input_tokens", 0) or 0
        if cache_created or cache_read:
            logger.info(
                "Claude prompt cache: created=%d read=%d input=%d model=%s",
                cache_created,
                cache_read,
                input_tokens,
                model,
            )

    response_text = "".join(response_parts)
    return response_text, input_tokens, output_tokens


# ── Agent tool loop ──────────────────────────────────────────────────────────


def _thinking_for(model: str) -> dict:
    """Adaptive thinking; a readable summary where the model offers one.

    Opus 4.8 defaults to omitting the summary text, so ask for it (it is
    what the live status line shows while the model reasons). Opus 4.6
    and Sonnet 4.6 already summarize and do not take the display key.
    """
    if "-4-6" in model:
        return {"type": "adaptive"}
    return {"type": "adaptive", "display": "summarized"}


def send_to_claude_with_tools(
    system_context,
    messages: list[dict],
    tools: list[dict],
    execute_batch,
    model: str = "claude-opus-4-8",
    *,
    max_turns: int = 30,
    is_cancelled: Callable[[], bool] | None = None,
    on_text: Callable[[str], None] | None = None,
    on_thinking: Callable[[str], None] | None = None,
    on_turn: Callable[[TurnUsage], None] | None = None,
    on_note: Callable[[str], None] | None = None,
    effort: str = "high",
    max_tokens: int = 16_000,
) -> LoopResult:
    """Agentic variant of send_to_claude: a manual tool-use loop.

    Each model turn streams; its tool_use blocks are executed together by
    ``execute_batch(calls) -> outcomes`` (agent_tools) and answered in one
    user message of tool_result blocks in block order. The assistant turn
    is echoed back verbatim, thinking blocks included, which is what
    makes the next turn valid. Loops until the model stops calling tools.

    Callbacks: ``on_text(text_so_far)`` for the turn's prose as it
    streams, ``on_thinking(summary_so_far)`` for the thinking summary,
    ``on_turn(TurnUsage)`` when a turn's usage is known, ``on_note(text)``
    when the loop intervenes (forced answer, retried turn). Cancellation
    raises InterruptedError, same as send_to_claude.

    The system prompt and tools stay byte-stable across turns and a
    rolling breakpoint follows the newest message, so each turn reads the
    prior turns from the prompt cache.
    """
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    convo = _format_messages(messages)
    # Block form on the newest message so the rolling marker can land on
    # it; plain-string history would leave the first tool turn unmarked
    # and the second turn re-billed in full.
    if convo and isinstance(convo[-1]["content"], str):
        convo[-1] = {
            "role": convo[-1]["role"],
            "content": [{"type": "text", "text": convo[-1]["content"]}],
        }
    system = _build_system(system_context)

    result = LoopResult()
    budget_strikes = 0
    force_answer = False
    retried_overflow = False

    for turn in range(1, max_turns + 2):
        _roll_message_cache_marker(convo)
        kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=convo,
            thinking=_thinking_for(model),
            output_config={"effort": effort},
        )
        if force_answer:
            kwargs["tool_choice"] = {"type": "none"}

        text_parts: list[str] = []
        thinking_parts: list[str] = []
        started = time.time()
        with client.messages.stream(**kwargs) as stream:
            for event in stream:
                if is_cancelled and is_cancelled():
                    raise InterruptedError("Request cancelled")
                if getattr(event, "type", "") != "content_block_delta":
                    continue
                delta = event.delta
                delta_type = getattr(delta, "type", "")
                if delta_type == "text_delta":
                    text_parts.append(delta.text)
                    if on_text:
                        on_text("".join(text_parts))
                elif delta_type == "thinking_delta":
                    thinking_parts.append(delta.thinking)
                    if on_thinking and delta.thinking.strip():
                        on_thinking("".join(thinking_parts))
            final = stream.get_final_message()

        usage = final.usage
        tool_blocks = [b for b in final.content if getattr(b, "type", "") == "tool_use"]
        turn_usage = TurnUsage(
            turn=turn,
            input=usage.input_tokens or 0,
            output=usage.output_tokens or 0,
            cache_read=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            tool_calls=len(tool_blocks),
            seconds=round(time.time() - started, 2),
            stop_reason=final.stop_reason or "",
        )
        result.add_turn(turn_usage)
        if on_turn:
            on_turn(turn_usage)
        if turn_usage.cache_read or turn_usage.cache_write:
            logger.info(
                "Claude agent cache created=%d read=%d turn_input=%d model=%s",
                turn_usage.cache_write,
                turn_usage.cache_read,
                turn_usage.input,
                model,
            )

        result.text = "".join(text_parts)
        result.stop_reason = final.stop_reason or ""

        if final.stop_reason == "refusal":
            details = getattr(final, "stop_details", None)
            if details is not None:
                result.stop_details = {
                    "category": getattr(details, "category", None),
                    "explanation": getattr(details, "explanation", None),
                }
            break

        if final.stop_reason == "max_tokens" and tool_blocks and not retried_overflow:
            # The turn ran out of room mid tool calls; they are unusable.
            # Ask for a shorter turn once instead of echoing a broken one.
            retried_overflow = True
            if on_note:
                on_note("The turn hit the output limit; asking for a shorter one")
            convo.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Your last turn hit the output limit and its "
                                "tool calls were discarded. Make fewer calls "
                                "per turn and keep prose short."
                            ),
                        }
                    ],
                }
            )
            continue

        if final.stop_reason != "tool_use" or not tool_blocks:
            break

        # Echo the assistant turn back verbatim (text, thinking, tool_use).
        convo.append(
            {
                "role": "assistant",
                "content": [
                    block.model_dump(exclude_unset=True) for block in final.content
                ],
            }
        )

        if is_cancelled and is_cancelled():
            raise InterruptedError("Request cancelled")
        if hasattr(execute_batch, "set_turn"):
            execute_batch.set_turn(turn)
        calls = [{"id": b.id, "name": b.name, "input": b.input} for b in tool_blocks]
        outcomes = execute_batch(calls)
        results = [
            {
                "type": "tool_result",
                "tool_use_id": outcome["id"],
                "content": outcome["content"],
                "is_error": bool(outcome.get("is_error")),
            }
            for outcome in outcomes
        ]

        budget_strikes = (
            budget_strikes + 1 if batch_is_all_budget_errors(outcomes) else 0
        )
        if budget_strikes >= 2 or turn >= max_turns:
            force_answer = True
            result.forced_answer = True
            results.append({"type": "text", "text": FORCED_ANSWER_NOTE})
            if on_note:
                on_note("Tool budget exhausted; asking for the answer")
        convo.append({"role": "user", "content": results})

    return result
