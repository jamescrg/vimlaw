"""Research mode is retired: conversations run the classic analysis path
only, and the chat header carries a static model badge instead of the
Mode/Model/Effort dropdowns. Old research conversations remain in the
database, so their trails and Authorities sections must keep rendering.
"""

import re

import pytest
from django.urls import reverse

from apps.case.ai.models import Conversation, Message

pytestmark = pytest.mark.django_db


@pytest.fixture
def _no_worker(monkeypatch):
    """Keep ai-send from launching the real background worker."""
    monkeypatch.setattr("apps.case.ai.views.process_ai_request", lambda *a, **k: None)


# --------------------------------------------------------------------------- #
# Retired controls
# --------------------------------------------------------------------------- #
def test_header_shows_static_model_badge(client, matter, user):
    conversation = Conversation.objects.create(
        matter=matter, title="T", llm="claude-opus", user=user
    )
    url = reverse("case:ai-conversation-view", args=[conversation.id])
    html = client.get(url).content.decode()
    assert "app-badge badge-lg ai-llm-claude-opus" in html
    assert conversation.get_llm_display() in html
    for retired in ("modePill", "effortPill", "llmPill", "llmMenu"):
        assert retired not in html


def test_new_chat_window_has_no_mode_controls(client, matter):
    url = reverse("case:ai-new-conversation-view", args=[matter.id])
    html = client.get(url, {"llm": "claude-opus", "title": "T"}).content.decode()
    assert "app-badge badge-lg ai-llm-claude-opus" in html
    for retired in ("modePill", "effortPill", "llmPill"):
        assert retired not in html


def test_legacy_research_conversation_gets_static_badge(client, matter, user):
    conversation = Conversation.objects.create(
        matter=matter, title="R", kind="research", user=user
    )
    url = reverse("case:ai-conversation-view", args=[conversation.id])
    html = client.get(url).content.decode()
    assert "app-badge badge-lg ai-llm-" in html
    assert "modePill" not in html


def test_send_ignores_kind_and_effort_params(client, matter, _no_worker):
    client.post(
        reverse("case:ai-send", args=[matter.id]),
        {
            "message": "What is the law?",
            "llm": "gemini-pro-latest",
            "kind": "research",
            "effort": "high",
        },
    )
    conversation = Conversation.objects.get()
    assert conversation.kind == "classic"
    assert conversation.effort == "medium"


def test_send_to_legacy_research_conversation_works(client, matter, user, _no_worker):
    """Old research conversations accept new messages (which now run the
    classic path); the stored kind stays as historical provenance."""
    conversation = Conversation.objects.create(
        matter=matter, title="R", kind="research", user=user
    )
    response = client.post(
        reverse("case:ai-send", args=[matter.id]),
        {
            "message": "Follow-up",
            "llm": "gemini-pro-latest",
            "conversation_id": conversation.id,
        },
    )
    assert response.status_code == 200
    conversation.refresh_from_db()
    assert conversation.kind == "research"


# --------------------------------------------------------------------------- #
# The new-conversation modal (title + model only)
# --------------------------------------------------------------------------- #
def _prompt_html(client, matter, llm="claude-opus"):
    url = reverse("case:ai-new-conversation-prompt", args=[matter.id])
    response = client.get(url, {"llm": llm})
    assert response.status_code == 200
    return response.content.decode()


def test_modal_has_no_mode_controls(client, matter):
    html = _prompt_html(client, matter)
    assert 'name="kind"' not in html
    assert "research-depth" not in html


def test_modal_keeps_requested_llm(client, matter):
    html = _prompt_html(client, matter, llm="claude-opus")
    assert re.search(r'value="claude-opus"\s+selected', html)
    assert not re.search(r'value="gemini-pro-latest"\s+selected', html)


def test_modal_model_sits_above_name(client, matter):
    html = _prompt_html(client, matter)
    assert html.index("new-conversation-llm") < html.index("new-conversation-title")


def test_modal_launch_uses_model_select():
    """The launch JS must read the select, not the sticky template value."""
    import pathlib

    source = pathlib.Path("templates/case/ai/new-conversation-modal.html").read_text()
    assert "getElementById('new-conversation-llm').value" in source


# --------------------------------------------------------------------------- #
# Historical research messages keep rendering
# --------------------------------------------------------------------------- #
def test_cited_authorities_only_grounded_cases(matter, user):
    conversation = Conversation.objects.create(
        matter=matter, title="R", kind="research", user=user
    )
    message = Message.objects.create(
        conversation=conversation,
        role="assistant",
        content="Answer.",
        research_trail=[
            {
                "type": "abstract",
                "cluster_id": 1,
                "case_name": "Birg v. Emory",
                "citation": "",
                "abstract": "CASE: Birg...",
            },
            {
                "type": "read",
                "cluster_id": 2,
                "case_name": "Toles",
                "citation": "300 Ga. App. 1",
            },
            {"type": "skim", "cluster_id": 3, "case_name": "Unused v. Case"},
            {"type": "grounding", "cited_clusters": [1, 2]},
        ],
    )
    auths = message.cited_authorities()
    assert [a["cluster_id"] for a in auths] == [1, 2]
    assert auths[0]["abstract"].startswith("CASE: Birg")
    assert auths[1]["case_name"] == "Toles"
    assert all(a["cluster_id"] != 3 for a in auths)


def test_legacy_trail_and_authorities_render(client, matter, user):
    conversation = Conversation.objects.create(
        matter=matter, title="R", kind="research", user=user
    )
    Message.objects.create(
        conversation=conversation,
        role="assistant",
        content="Answer.",
        research_trail=[
            {
                "type": "search",
                "query": 'partition AND "joint tenancy"',
                "result_count": 8,
                "results": [{"case_name": "Hit One", "cluster_id": 11}],
            },
            {"type": "read", "cluster_id": 2, "case_name": "Toles"},
            {
                "type": "abstract",
                "cluster_id": 1,
                "case_name": "Birg v. Emory",
                "citation": "",
                "abstract": "CASE: Birg brief text",
            },
            {
                "type": "treatment",
                "cluster_id": 1,
                "case_name": "Birg v. Emory",
                "checked": True,
                "has_negative_treatment": False,
            },
            {"type": "grounding", "cited_clusters": [1]},
        ],
    )
    url = reverse("case:ai-conversation-view", args=[conversation.id])
    html = client.get(url).content.decode()
    assert "Research trail" in html
    assert "Read and briefed" in html
    assert "Authorities" in html
    assert "Birg brief text" in html
    # The trail names searches without linking every hit.
    assert "ai-research-hits" not in html
    assert "Hit One" not in html
