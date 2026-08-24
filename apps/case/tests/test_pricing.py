"""Cost estimation behind the status bar's dollar segments."""

import pytest

from apps.case.ai.models import Conversation, Message
from apps.case.ai.pricing import conversation_cost, estimate_cost
from apps.case.templatetags.ai_extras import usd


def test_claude_cache_economics():
    # The Fable smoke run on CB Roberts: write-heavy first turn, cached rest.
    cost = estimate_cost(
        "claude-fable", 256_115, 5_230, cache_read=154_058, cache_write=102_051
    )
    assert abs(cost - 1.69) < 0.01


def test_classic_uncached():
    assert estimate_cost("claude-opus", 100_000, 2_000) == pytest.approx(0.55)


def test_gemini_long_context_tier():
    short = estimate_cost("gemini-pro-latest", 100_000, 1_000)
    long = estimate_cost("gemini-pro-latest", 250_000, 1_000)
    assert short == pytest.approx(0.135)
    assert long == pytest.approx(0.64)  # 2.50/M input, 15/M output


def test_unknown_model_is_none():
    assert estimate_cost("mystery-model", 1000, 1000) is None


def test_usd_formatting():
    assert usd(0.55) == "$0.55"
    assert usd(1.694) == "$1.69"
    assert usd(0.004) == "<$0.01"
    assert usd(0) == "$0.00"
    assert usd(None) == ""


@pytest.mark.django_db
def test_conversation_cost_totals_and_last(matter, user):
    conversation = Conversation.objects.create(
        matter=matter, title="A", user=user, kind="agent", llm="claude-opus"
    )
    # Classic-shaped message: raw totals, priced uncached.
    Message.objects.create(
        conversation=conversation,
        role="assistant",
        content="x",
        input_tokens=100_000,
        output_tokens=2_000,
    )
    # Agent-shaped message: the cache split prices the discount in.
    Message.objects.create(
        conversation=conversation,
        role="assistant",
        content="y",
        input_tokens=200_000,
        output_tokens=4_000,
        agent_run={
            "usage": {
                "input": 200_000,
                "output": 4_000,
                "cache_read": 150_000,
                "cache_write": 40_000,
            }
        },
    )
    cost = conversation_cost(conversation)
    # Second message: 10k uncached + 40k written + 150k read + 4k out.
    assert cost["last"] == pytest.approx(0.475)
    assert cost["total"] == pytest.approx(0.55 + 0.475)


@pytest.mark.django_db
def test_conversation_cost_none_when_unpriced(matter, user):
    conversation = Conversation.objects.create(
        matter=matter, title="A", user=user, llm="claude-opus"
    )
    Message.objects.create(conversation=conversation, role="assistant", content="x")
    assert conversation_cost(conversation) is None
