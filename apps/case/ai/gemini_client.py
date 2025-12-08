"""
Google Gemini API client for AI chat.

Uses native Gemini SDK with streaming and thought summaries.
"""

from typing import Callable

from django.conf import settings
from google.genai import types

from google import genai


def send_to_gemini_streaming(
    system_context: str,
    messages: list[dict],
    model: str = "gemini-2.5-flash",
    on_thought: Callable[[str], None] | None = None,
) -> tuple[str, int, int]:
    """
    Send a conversation to Gemini with streaming and thought summaries.

    Args:
        system_context: The system prompt with matter context
        messages: List of {"role": "user"|"assistant", "content": str}
        model: Gemini model to use (gemini-2.5-flash or gemini-2.5-pro)
        on_thought: Optional callback called with each thought summary

    Returns:
        tuple of (response_text, input_tokens, output_tokens)

    Raises:
        google.genai.errors.APIError: If the API call fails
    """
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    # Build conversation contents
    contents = []

    # Add conversation history
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        contents.append(
            types.Content(role=role, parts=[types.Part(text=msg["content"])])
        )

    # Configure with thinking enabled
    config = types.GenerateContentConfig(
        system_instruction=system_context,
        thinking_config=types.ThinkingConfig(include_thoughts=True),
        http_options=types.HttpOptions(timeout=300_000),  # 5 min timeout in ms
    )

    # Stream response and collect parts
    response_parts = []
    input_tokens = 0
    output_tokens = 0

    for chunk in client.models.generate_content_stream(
        model=model,
        contents=contents,
        config=config,
    ):
        # Extract token usage from final chunk
        if chunk.usage_metadata:
            input_tokens = chunk.usage_metadata.prompt_token_count or 0
            output_tokens = chunk.usage_metadata.candidates_token_count or 0

        if not chunk.candidates:
            continue

        for part in chunk.candidates[0].content.parts:
            if not part.text:
                continue

            if part.thought:
                # This is a thought summary - call the callback
                if on_thought:
                    on_thought(part.text)
            else:
                # This is part of the actual response
                response_parts.append(part.text)

    response_text = "".join(response_parts)

    return response_text, input_tokens, output_tokens


def send_to_gemini(
    system_context: str, messages: list[dict], model: str = "gemini-2.5-flash"
) -> tuple[str, int, int]:
    """
    Send a conversation to Gemini and get a response (non-streaming).

    This is kept for backwards compatibility.

    Args:
        system_context: The system prompt with matter context
        messages: List of {"role": "user"|"assistant", "content": str}
        model: Gemini model to use (gemini-2.5-flash or gemini-2.5-pro)

    Returns:
        tuple of (response_text, input_tokens, output_tokens)
    """
    return send_to_gemini_streaming(system_context, messages, model, on_thought=None)
