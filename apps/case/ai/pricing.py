"""
Estimated API cost per exchange, for the chat status bar.

List rates in USD per million tokens, with the cache economics applied:
Anthropic bills cache writes at 1.25x and cache reads at 0.10x the input
rate; Gemini's implicit cache bills cached prompt tokens at roughly a
quarter of the input rate, and Gemini Pro bills prompts over 200k tokens
at a higher tier. ``input_tokens`` here always means the whole prompt
(cache reads and writes included), matching TurnUsage and
Message.input_tokens. These are estimates for orientation, not invoices.
"""

# Picker key -> (input, output) USD per million tokens.
PRICING = {
    "claude": (3.00, 15.00),  # Sonnet 4.6
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus": (5.00, 25.00),  # Opus 4.8
    "claude-opus-4-6": (5.00, 25.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-fable": (10.00, 50.00),
    "gemini-flash": (0.30, 2.50),
    "gemini-pro": (1.25, 10.00),
    "gemini-pro-latest": (1.25, 10.00),
}

# Gemini Pro tiers up for prompts over 200k tokens.
GEMINI_LONG_CONTEXT = {
    "gemini-pro": (2.50, 15.00),
    "gemini-pro-latest": (2.50, 15.00),
}
GEMINI_LONG_THRESHOLD = 200_000

CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10
GEMINI_CACHE_READ_MULTIPLIER = 0.25


def estimate_cost(llm, input_tokens, output_tokens, cache_read=0, cache_write=0):
    """Estimated USD for one exchange; None for models without a rate."""
    rates = PRICING.get(llm)
    if rates is None:
        return None
    input_tokens = input_tokens or 0
    output_tokens = output_tokens or 0
    cache_read = cache_read or 0
    cache_write = cache_write or 0

    if llm.startswith("gemini"):
        in_rate, out_rate = rates
        if input_tokens > GEMINI_LONG_THRESHOLD and llm in GEMINI_LONG_CONTEXT:
            in_rate, out_rate = GEMINI_LONG_CONTEXT[llm]
        uncached = max(0, input_tokens - cache_read)
        input_cost = (
            uncached * in_rate + cache_read * in_rate * GEMINI_CACHE_READ_MULTIPLIER
        )
        return (input_cost + output_tokens * out_rate) / 1_000_000

    in_rate, out_rate = rates
    uncached = max(0, input_tokens - cache_read - cache_write)
    input_cost = (
        uncached * in_rate
        + cache_write * in_rate * CACHE_WRITE_MULTIPLIER
        + cache_read * in_rate * CACHE_READ_MULTIPLIER
    )
    return (input_cost + output_tokens * out_rate) / 1_000_000


def message_cost(message, llm):
    """Estimated USD for one assistant message.

    Agent messages carry the cache split in agent_run.usage, so their
    caching discount prices in; classic messages store only the raw
    token totals and are treated as uncached (an overestimate when the
    provider cache hit).
    """
    usage = (message.agent_run or {}).get("usage") if message.agent_run else None
    if usage:
        return estimate_cost(
            llm,
            usage.get("input"),
            usage.get("output"),
            usage.get("cache_read"),
            usage.get("cache_write"),
        )
    if message.input_tokens is None and message.output_tokens is None:
        return None
    return estimate_cost(llm, message.input_tokens, message.output_tokens)


def conversation_cost(conversation):
    """{"total": x, "last": y} estimated USD across the conversation's
    assistant messages; None when nothing is priceable."""
    if conversation.llm not in PRICING:
        return None
    total = 0.0
    last = None
    for message in conversation.messages.filter(role="assistant").only(
        "input_tokens", "output_tokens", "agent_run"
    ):
        cost = message_cost(message, conversation.llm)
        if cost is None:
            continue
        total += cost
        last = cost
    if last is None:
        return None
    return {"total": total, "last": last}
