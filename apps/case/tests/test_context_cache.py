"""Tests for per-conversation context reuse (assemble_matter_context_with_selection)."""

import pytest
from django.core.cache import cache

from apps.case.ai import selector
from apps.case.ai.context import assemble_matter_context_with_selection
from apps.case.ai.models import Conversation
from apps.notes.models import Note

pytestmark = pytest.mark.django_db


@pytest.fixture
def conversation(matter):
    return Conversation.objects.create(matter=matter, title="Chat", llm="claude-opus")


@pytest.fixture
def manifest_counter(monkeypatch):
    calls = {"n": 0}

    def counting_build_manifest(*args, **kwargs):
        calls["n"] += 1
        return [], {}

    monkeypatch.setattr(selector, "build_manifest", counting_build_manifest)
    cache.clear()
    return calls


def assemble(matter, conversation, user, message):
    return assemble_matter_context_with_selection(
        matter,
        user_message=message,
        llm="claude-opus",
        user=user,
        conversation=conversation,
    )


def test_follow_up_reuses_context(user, matter, conversation, manifest_counter):
    first = assemble(matter, conversation, user, "analyze service of process")
    second = assemble(matter, conversation, user, "now save that to a note")
    assert manifest_counter["n"] == 1
    assert second == first


def test_material_change_rebuilds(user, matter, conversation, manifest_counter):
    assemble(matter, conversation, user, "question one")
    Note.objects.create(matter=matter, title="AI conclusion", content="text")
    assemble(matter, conversation, user, "question two")
    assert manifest_counter["n"] == 2


def test_conversations_do_not_share(user, matter, conversation, manifest_counter):
    other = Conversation.objects.create(matter=matter, title="Other", llm="claude-opus")
    assemble(matter, conversation, user, "question")
    assemble(matter, other, user, "question")
    assert manifest_counter["n"] == 2


def test_no_conversation_never_caches(user, matter, manifest_counter):
    assemble(matter, None, user, "nightly summary pass")
    assemble(matter, None, user, "nightly summary pass")
    assert manifest_counter["n"] == 2
