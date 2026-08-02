"""
Anthropic Claude API client for AI chat.

Uses streaming to support cancellation mid-request, and marks the system
prompt as cacheable so repeat messages in the same conversation benefit
from Anthropic's prompt-cache pricing (~10% of input cost on cache hits).
"""

import logging
from typing import Callable

import anthropic
from django.conf import settings

logger = logging.getLogger(__name__)


# Anthropic's prompt cache has a per-model minimum prefix: 1024 tokens on
# Sonnet 4.6 and Opus 4.8, 4096 on Opus 4.6. We use a character heuristic
# (~4 chars/token) that clears the 1024 minimum and avoids marking small
# system prompts; below it we fall back to the plain string form. On Opus
# 4.6 a marked prompt under ~16k chars simply doesn't cache — the marker is
# ignored, not billed — so matter contexts that small show no cache lines in
# the log. Every real matter context clears it comfortably.
_ANTHROPIC_CACHE_MIN_CHARS = 5000


def _build_system(system_context: str):
    """Return the `system=` argument for messages.stream.

    For large prompts, returns a content block list with an ephemeral
    cache_control marker so Anthropic caches the prefix for ~5 minutes and
    subsequent identical prefixes pay ~10% of the input rate. For smaller
    prompts, returns the plain string (no caching — the cache-write premium
    isn't justified below the minimum cacheable length).
    """
    if system_context and len(system_context) >= _ANTHROPIC_CACHE_MIN_CHARS:
        return [
            {
                "type": "text",
                "text": system_context,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    return system_context


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

    # Format messages for Anthropic API
    formatted_messages = [
        {"role": msg["role"], "content": msg["content"]} for msg in messages
    ]

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


def send_to_claude_with_tools(
    system_context: str,
    messages: list[dict],
    tools: list[dict],
    execute_tool: Callable[[str, dict], tuple[str, dict | None]],
    model: str = "claude-opus-4-8",
    max_tool_calls: int = 12,
    is_cancelled: Callable[[], bool] | None = None,
    on_activity: Callable[[str, dict], None] | None = None,
) -> tuple[str, int, int, list[dict]]:
    """Agentic variant of send_to_claude: a manual tool-use loop.

    The model may call the provided tools (research chat: CourtListener
    search/read/treatment); each tool_use round is executed via
    ``execute_tool(name, input) -> (result_json, trail_event)`` and fed
    back as tool_result blocks until the model stops with a final answer.

    ``on_activity(kind, payload)`` fires for "text" (assistant prose as it
    streams, e.g. the research plan) and "tool_call" (before execution) so
    the caller can surface live status. Cancellation raises
    InterruptedError, same as send_to_claude.

    Returns (final_text, input_tokens, output_tokens, trail_events).
    Tokens accumulate across every model turn. The system prompt and tools
    stay byte-stable across turns so the prompt-cache prefix keeps hitting.
    """
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    convo = [{"role": msg["role"], "content": msg["content"]} for msg in messages]
    system = _build_system(system_context)

    input_tokens = 0
    output_tokens = 0
    tool_calls_used = 0
    trail_events: list[dict] = []
    final_text = ""

    # Ceiling on model turns: even if the model ignores the budget notice,
    # the loop terminates.
    for _turn in range(max_tool_calls + 4):
        text_parts = []
        with client.messages.stream(
            model=model,
            max_tokens=8192,
            system=system,
            tools=tools,
            messages=convo,
        ) as stream:
            for text in stream.text_stream:
                if is_cancelled and is_cancelled():
                    raise InterruptedError("Request cancelled")
                text_parts.append(text)
                if on_activity and text.strip():
                    on_activity("text", {"text": "".join(text_parts)})
            final_message = stream.get_final_message()

        input_tokens += final_message.usage.input_tokens
        output_tokens += final_message.usage.output_tokens
        cache_read = getattr(final_message.usage, "cache_read_input_tokens", 0) or 0
        if cache_read:
            logger.info(
                "Claude research cache read=%d turn_input=%d model=%s",
                cache_read,
                final_message.usage.input_tokens,
                model,
            )

        final_text = "".join(text_parts)

        if final_message.stop_reason != "tool_use":
            break

        # Echo the assistant turn back verbatim (text + tool_use blocks).
        convo.append(
            {
                "role": "assistant",
                "content": [
                    block.model_dump(exclude_unset=True)
                    for block in final_message.content
                ],
            }
        )

        results = []
        for block in final_message.content:
            if getattr(block, "type", "") != "tool_use":
                continue
            if is_cancelled and is_cancelled():
                raise InterruptedError("Request cancelled")
            if on_activity:
                on_activity("tool_call", {"name": block.name, "input": block.input})
            if tool_calls_used >= max_tool_calls:
                result_json = (
                    '{"error": "Tool budget exhausted. Provide your best '
                    'answer from the opinions already read."}'
                )
                event = None
            else:
                tool_calls_used += 1
                result_json, event = execute_tool(block.name, block.input)
            if event:
                trail_events.append(event)
                if on_activity:
                    on_activity("tool_result", event)
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_json,
                    "is_error": '"error"' in result_json[:12],
                }
            )
        convo.append({"role": "user", "content": results})

    return final_text, input_tokens, output_tokens, trail_events
