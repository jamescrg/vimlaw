"""
Google Gemini API client for AI chat.

Uses native Gemini SDK with streaming and thought summaries. Supports
cancellation mid-request to stop billing. For conversation-scoped calls,
the system prompt is pushed into a Gemini `cachedContents` object so
subsequent messages in the same conversation reuse the cached prefix at
the reduced-input-token rate.
"""

import hashlib
import logging
import time
from typing import Callable

from django.conf import settings
from django.core.cache import cache as django_cache
from google.genai import types

from google import genai

logger = logging.getLogger(__name__)


# Gemini caches require a minimum number of tokens (4,096 on 2.5 Flash,
# 32,768 on 2.5 Pro per Google's docs). Use the higher floor as a
# conservative character heuristic so we never attempt to cache a prompt
# too small for any supported model.
_GEMINI_CACHE_MIN_CHARS = 130_000  # ~32k tokens at ~4 chars/token

# How long a Gemini cache lives server-side. Google bills per-hour of
# storage × cached tokens, so keep this short — long enough to cover a
# typical chat session, short enough that forgotten conversations don't
# accumulate storage cost.
_GEMINI_CACHE_TTL_SECONDS = 600  # 10 minutes


def _cache_entry_key(conversation_id: int, model: str, system_context: str) -> str:
    """Django-cache key for tracking a Gemini cachedContents handle."""
    sys_hash = hashlib.sha256(system_context.encode("utf-8")).hexdigest()[:16]
    return f"gemini_cache_{conversation_id}_{model}_{sys_hash}"


def _get_or_create_gemini_cache(
    client: "genai.Client",
    model: str,
    system_context: str,
    conversation_id: int | None,
) -> str | None:
    """Return a Gemini cachedContents resource name for this system prompt.

    Looks up a stored handle keyed by (conversation_id, model, system_hash).
    Creates a new cache if none exists (or the stored one has expired),
    stashes the new handle in Django's cache, and returns its name.
    Returns None when caching isn't viable for this request (no
    conversation_id, system prompt too small, or the create call fails).
    """
    if conversation_id is None:
        return None
    if not system_context or len(system_context) < _GEMINI_CACHE_MIN_CHARS:
        return None

    entry_key = _cache_entry_key(conversation_id, model, system_context)
    entry = django_cache.get(entry_key)
    if entry and entry.get("expires_at", 0) > time.time():
        return entry["name"]

    try:
        cached = client.caches.create(
            model=f"models/{model}",
            config=types.CreateCachedContentConfig(
                system_instruction=system_context,
                ttl=f"{_GEMINI_CACHE_TTL_SECONDS}s",
                display_name=f"conv-{conversation_id}",
            ),
        )
    except Exception as exc:
        logger.warning("Gemini cache create failed (model=%s): %s", model, exc)
        return None

    expires_at = time.time() + _GEMINI_CACHE_TTL_SECONDS - 15  # small safety margin
    django_cache.set(
        entry_key,
        {"name": cached.name, "expires_at": expires_at},
        timeout=_GEMINI_CACHE_TTL_SECONDS,
    )
    logger.info(
        "Gemini cache created: name=%s model=%s conv=%s",
        cached.name,
        model,
        conversation_id,
    )
    return cached.name


def send_to_gemini_streaming(
    system_context: str,
    messages: list[dict],
    model: str = "gemini-2.5-flash",
    on_thought: Callable[[str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    conversation_id: int | None = None,
) -> tuple[str, int, int]:
    """
    Send a conversation to Gemini with streaming and thought summaries.

    Checks for cancellation on each chunk to allow stopping mid-request.

    Args:
        system_context: The system prompt with matter context
        messages: List of {"role": "user"|"assistant", "content": str}
        model: Gemini model to use (gemini-2.5-flash or gemini-2.5-pro)
        on_thought: Optional callback called with each thought summary
        is_cancelled: Optional callback that returns True if request should be cancelled
        conversation_id: Optional conversation id. When provided (and the
            system prompt is large enough), the system prompt is cached
            via Gemini's cachedContents API and reused for subsequent
            messages in the same conversation.

    Returns:
        tuple of (response_text, input_tokens, output_tokens)

    Raises:
        google.genai.errors.APIError: If the API call fails
        InterruptedError: If the request was cancelled
    """
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    cached_name = _get_or_create_gemini_cache(
        client, model, system_context, conversation_id
    )

    # Build conversation contents
    contents = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        contents.append(
            types.Content(role=role, parts=[types.Part(text=msg["content"])])
        )

    # Build the config. When we have a cached_content handle, we reference
    # it by name and omit system_instruction (the cached object already
    # supplies it). Otherwise we send the system_instruction inline.
    if cached_name:
        config = types.GenerateContentConfig(
            cached_content=cached_name,
            thinking_config=types.ThinkingConfig(include_thoughts=True),
            http_options=types.HttpOptions(timeout=300_000),
        )
    else:
        config = types.GenerateContentConfig(
            system_instruction=system_context,
            thinking_config=types.ThinkingConfig(include_thoughts=True),
            http_options=types.HttpOptions(timeout=300_000),
        )

    response_parts = []
    input_tokens = 0
    output_tokens = 0

    try:
        chunk_iter = client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=config,
        )
    except Exception as exc:
        # If the provider rejected our cached_content handle (expired,
        # deleted server-side, wrong model, etc.), invalidate our stored
        # handle and retry once without cache so the user still gets a
        # response.
        if cached_name and conversation_id is not None:
            logger.warning(
                "Gemini cached_content rejected (%s); retrying without cache", exc
            )
            django_cache.delete(
                _cache_entry_key(conversation_id, model, system_context)
            )
            config = types.GenerateContentConfig(
                system_instruction=system_context,
                thinking_config=types.ThinkingConfig(include_thoughts=True),
                http_options=types.HttpOptions(timeout=300_000),
            )
            chunk_iter = client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=config,
            )
        else:
            raise

    cached_tokens_seen = 0
    try:
        for chunk in chunk_iter:
            if is_cancelled and is_cancelled():
                raise InterruptedError("Request cancelled")

            if chunk.usage_metadata:
                input_tokens = chunk.usage_metadata.prompt_token_count or 0
                output_tokens = chunk.usage_metadata.candidates_token_count or 0
                cached_tokens_seen = (
                    getattr(chunk.usage_metadata, "cached_content_token_count", 0) or 0
                )

            if not chunk.candidates:
                continue

            for part in chunk.candidates[0].content.parts:
                if not part.text:
                    continue
                if part.thought:
                    if on_thought:
                        on_thought(part.text)
                else:
                    response_parts.append(part.text)
    except InterruptedError:
        raise
    except Exception:
        # If streaming fails while we were referencing a cached handle,
        # invalidate our stored handle so the next message doesn't reuse a
        # possibly-bad cache. Then re-raise — we can't recover mid-stream.
        if cached_name and conversation_id is not None:
            django_cache.delete(
                _cache_entry_key(conversation_id, model, system_context)
            )
        raise

    if cached_tokens_seen:
        logger.info(
            "Gemini prompt cache read: cached=%d total_input=%d model=%s conv=%s",
            cached_tokens_seen,
            input_tokens,
            model,
            conversation_id,
        )

    response_text = "".join(response_parts)
    return response_text, input_tokens, output_tokens


def send_to_gemini(
    system_context: str,
    messages: list[dict],
    model: str = "gemini-2.5-flash",
    conversation_id: int | None = None,
) -> tuple[str, int, int]:
    """
    Send a conversation to Gemini and get a response (non-streaming).

    This is kept for backwards compatibility.

    Args:
        system_context: The system prompt with matter context
        messages: List of {"role": "user"|"assistant", "content": str}
        model: Gemini model to use (gemini-2.5-flash or gemini-2.5-pro)
        conversation_id: Optional conversation id for prompt caching.

    Returns:
        tuple of (response_text, input_tokens, output_tokens)
    """
    return send_to_gemini_streaming(
        system_context,
        messages,
        model,
        on_thought=None,
        conversation_id=conversation_id,
    )
