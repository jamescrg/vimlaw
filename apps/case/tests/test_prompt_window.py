"""Tests for the prompt-size guards: exact-count trimming at the Claude send
site and tier-wise shedding of always-included content during assembly."""

import pytest
from django.core.cache import cache

from apps.case.ai import selector, tasks
from apps.case.ai.context import assemble_matter_context_with_selection
from apps.case.ai.models import Conversation
from apps.case.ai.selector import estimate_tokens
from apps.case.ai.tasks import PromptTooLargeError, fit_prompt_to_window
from apps.case.models import Document

pytestmark = pytest.mark.django_db


# ── send-site guard ──────────────────────────────────────────────────────


def _history(n, size):
    return [{"role": "user", "content": "x" * size} for _ in range(n)]


def test_small_prompt_skips_exact_count(monkeypatch):
    calls = []
    monkeypatch.setattr(
        tasks, "count_claude_tokens", lambda *a, **k: calls.append(a) or 10
    )
    history = _history(3, 100)
    trimmed, tokens = fit_prompt_to_window(
        "ctx", history, "claude-opus", lambda line: 0
    )
    assert calls == []
    assert len(trimmed) == 3
    assert tokens == estimate_tokens("ctx") + 3 * estimate_tokens("x" * 100)


def test_exact_count_trims_history_when_estimate_was_low(monkeypatch):
    """The estimate clears the 80% ceiling but the real tokenizer says the
    prompt is over the window: history is trimmed against the exact count
    and re-counted until it fits."""
    monkeypatch.setitem(selector.MODEL_HARD_LIMITS, "claude-opus", 10_000)
    counts = []

    def fake_count(context_text, history, model):
        # "Real" tokenizer is 1.6x denser than the estimate.
        n = int(
            (
                estimate_tokens(context_text)
                + sum(estimate_tokens(m["content"]) for m in history)
            )
            * 1.6
        )
        counts.append(n)
        return n

    monkeypatch.setattr(tasks, "count_claude_tokens", fake_count)
    # Estimate: context 4,800 + 8 messages x 540 = 9,120; the estimate pass
    # trims to 8,000, the exact pass (x1.6) then finds it over 9,800 and
    # trims further until the re-count fits.
    history = _history(8, 1350)
    log = []
    trimmed, tokens = fit_prompt_to_window(
        "c" * 12_000, history, "claude-opus", log.append
    )
    assert len(counts) >= 2
    assert tokens == counts[-1]
    assert tokens <= 9_800
    assert 1 <= len(trimmed) < 8
    assert any("Exact prompt size" in line for line in log)


def test_context_alone_too_large_raises(monkeypatch):
    monkeypatch.setitem(selector.MODEL_HARD_LIMITS, "claude-opus", 10_000)
    monkeypatch.setattr(tasks, "count_claude_tokens", lambda *a, **k: 15_000)
    with pytest.raises(PromptTooLargeError) as excinfo:
        fit_prompt_to_window(
            "c" * 24_000, _history(2, 100), "claude-opus", lambda line: 0
        )
    assert "too large for this model" in str(excinfo.value)
    assert "15,000" in str(excinfo.value)


def test_count_failure_falls_back_to_estimate(monkeypatch):
    monkeypatch.setitem(selector.MODEL_HARD_LIMITS, "claude-opus", 10_000)
    monkeypatch.setattr(tasks, "count_claude_tokens", lambda *a, **k: None)
    history = _history(2, 100)
    trimmed, tokens = fit_prompt_to_window(
        "c" * 15_000, history, "claude-opus", lambda line: 0
    )
    assert len(trimmed) == 2
    assert tokens == estimate_tokens("c" * 15_000) + 2 * estimate_tokens("x" * 100)


# ── assembly guard ───────────────────────────────────────────────────────


@pytest.fixture
def conversation(matter):
    return Conversation.objects.create(matter=matter, title="Chat", llm="claude-opus")


@pytest.fixture(autouse=True)
def no_manifest(monkeypatch):
    monkeypatch.setattr(selector, "build_manifest", lambda *a, **k: ([], {}))
    cache.clear()


def _assemble(matter, conversation, user):
    return assemble_matter_context_with_selection(
        matter,
        user_message="q",
        llm="claude-opus",
        user=user,
        conversation=conversation,
    )


def _always_doc(matter, user, name, text, importance):
    doc = Document.objects.create(
        matter=matter,
        name=name,
        category="Evidence",
        created_by=user,
        ocr_text=text,
        importance=importance,
        ai_context="always",
    )
    # save() resets the OCR status for a file-less document; the context
    # builder only inlines text for completed/extracted documents.
    Document.objects.filter(pk=doc.pk).update(ocr_status="completed")
    return doc


def test_reference_tier_shed_before_high(user, matter, conversation, monkeypatch):
    _always_doc(matter, user, "Key memo", "keep me", 4)
    baseline = estimate_tokens(_assemble(matter, conversation, user))
    cache.clear()
    _always_doc(matter, user, "Old research", "r" * 40_000, 1)
    # Ceiling just above the baseline: the reference document cannot fit,
    # the high one can.
    monkeypatch.setitem(
        selector.MODEL_HARD_LIMITS, "claude-opus", int((baseline + 400) / 0.8)
    )
    context = _assemble(matter, conversation, user)
    assert "r" * 40_000 not in context
    assert "keep me" in context
    assert "## Omitted Materials" in context
    assert "- Document: Document [doc:" in context
    assert "Old research" in context
    assert "1 [REFERENCE] items omitted" in context


def test_critical_items_never_shed(user, matter, conversation, monkeypatch):
    _always_doc(matter, user, "Crux", "c" * 40_000, 5)
    monkeypatch.setitem(selector.MODEL_HARD_LIMITS, "claude-opus", 1_000)
    context = _assemble(matter, conversation, user)
    assert "c" * 40_000 in context
    assert "## Omitted Materials" not in context
