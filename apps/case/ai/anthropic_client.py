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


# Anthropic's prompt cache requires a minimum of 1024 tokens for Sonnet/Opus
# (2048 for Haiku). We use a character heuristic (~4 chars/token) that
# comfortably clears the Sonnet minimum and avoids wasting a cache-write on
# small system prompts. Below this, we fall back to the plain string form.
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

    Sonnet 4.6 and Opus 4.8 expose a 1M-token context window on this account
    without any beta header. The selector's MODEL_CONTEXT_LIMITS is a soft
    cap on auto-selected content; the assembler enforces a separate hard
    ceiling so the total prompt stays under the model window even when
    always-included content (highlights, facts, notes, reference convos)
    inflates the fixed portion.

    Args:
        system_context: The system prompt with matter context
        messages: List of {"role": "user"|"assistant", "content": str}
        model: Claude model to use (claude-sonnet-4-6 or claude-opus-4-8)
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
