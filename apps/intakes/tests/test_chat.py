import json

import pytest

from apps.case.ai.models import Conversation, Message
from apps.case.ai.status import status_cache as cache
from apps.intakes.models import Note

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _inline_threads(monkeypatch):
    """Run the chat worker thread synchronously."""
    import threading

    class InlineThread:
        def __init__(self, target=None, args=(), daemon=None):
            self._target = target
            self._args = args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(threading, "Thread", InlineThread)


@pytest.fixture
def mock_gemini(monkeypatch):
    """Mock both the streaming (chat) and plain (summary) Gemini calls."""

    def _set(response="The neighbor's claim looks weak.", fail_summary=False):
        def fake_streaming(system, messages, **kwargs):
            return response, 100, 50

        def fake_plain(system, messages, **kwargs):
            if fail_summary:
                raise RuntimeError("Gemini unavailable")
            return "We concluded the fence claim is viable.", 10, 5

        monkeypatch.setattr(
            "apps.case.ai.gemini_client.send_to_gemini_streaming", fake_streaming
        )
        monkeypatch.setattr("apps.case.ai.gemini_client.send_to_gemini", fake_plain)

    return _set


def send(client, intake, text="Is this fence claim viable?"):
    return client.post(f"/intakes/{intake.id}/chat/send", {"message": text})


def test_window_renders_new_and_resumed(client, intake, mock_gemini):
    response = client.get(f"/intakes/{intake.id}/chat/")
    assert response.status_code == 200
    assert b"Intake Chat" in response.content
    assert intake.name.encode() in response.content

    mock_gemini()
    send(client, intake)
    response = client.get(f"/intakes/{intake.id}/chat/")
    assert b"Is this fence claim viable?" in response.content


def test_send_creates_intake_conversation(client, intake, mock_gemini):
    mock_gemini()
    response = send(client, intake)
    assert response.status_code == 200

    conversation = Conversation.objects.get()
    assert conversation.intake_id == intake.id
    assert conversation.matter_id is None
    assert conversation.llm == "gemini-pro-latest"
    assert conversation.vet_citations is False
    assert conversation.messages.filter(role="user").count() == 1
    # The inline worker completed and stashed the response in cache
    status = cache.get(f"ai_status_{conversation.id}")
    assert status["status"] == "complete"
    assert status["citations"] == []


def test_second_send_reuses_conversation(client, intake, mock_gemini):
    mock_gemini()
    send(client, intake)
    send(client, intake, "What about adverse possession?")
    assert Conversation.objects.count() == 1
    assert Message.objects.filter(role="user").count() == 2


def test_status_completes_intake_conversation(client, intake, mock_gemini):
    """The shared case:ai-status endpoint accepts a matterless conversation
    and does not spawn the matter-only summary thread (threads run inline
    here, so a spawned summary would overwrite conversation.summary)."""
    mock_gemini()
    send(client, intake)
    conversation = Conversation.objects.get()

    response = client.get(f"/case/ai/status/{conversation.id}/")
    assert response.status_code == 200
    assistant = conversation.messages.get(role="assistant")
    assert "neighbor's claim looks weak" in assistant.content
    conversation.refresh_from_db()
    assert not conversation.summary


def test_end_posts_kosmos_note_and_deletes(client, intake, mock_gemini):
    mock_gemini()
    send(client, intake)
    conversation = Conversation.objects.get()
    client.get(f"/case/ai/status/{conversation.id}/")

    response = client.post(f"/intakes/{intake.id}/chat/end")
    assert response.status_code == 200
    assert b"This chat has ended" in response.content

    note = Note.objects.get()
    assert note.intake_id == intake.id
    assert note.user.username == "kosmos"
    assert note.type == "Comment"
    assert "AI chat summary" in note.details
    assert "fence claim is viable" in note.details
    assert Conversation.objects.count() == 0


def test_end_failure_keeps_conversation(client, intake, mock_gemini):
    mock_gemini(fail_summary=True)
    send(client, intake)

    response = client.post(f"/intakes/{intake.id}/chat/end")
    assert b"Summary failed" in response.content
    assert Conversation.objects.count() == 1
    assert Note.objects.count() == 0


def test_discard_deletes_without_note(client, intake, mock_gemini):
    mock_gemini()
    send(client, intake)
    response = client.post(f"/intakes/{intake.id}/chat/discard")
    assert response.status_code == 200
    assert Conversation.objects.count() == 0
    assert Note.objects.count() == 0


def test_end_without_conversation_is_noop(client, intake):
    response = client.post(f"/intakes/{intake.id}/chat/end")
    assert response.status_code == 200
    assert Note.objects.count() == 0


# ── User-directed field updates ──────────────────────────────────────────────


def update_block(payload):
    return "Done.\n\n```update-intake\n" + json.dumps(payload) + "\n```"


def test_update_block_changes_fields(
    client, intake, practice_area, mock_gemini, monkeypatch
):
    monkeypatch.setattr(
        "apps.case.ai.gemini_client.send_to_gemini_streaming",
        lambda *a, **k: (
            update_block({"value": 75000, "practice_area": "general", "importance": 9}),
            10,
            5,
        ),
    )
    send(client, intake, "Set the value to 75k and area to General.")
    conversation = Conversation.objects.get()
    client.get(f"/case/ai/status/{conversation.id}/")

    intake.refresh_from_db()
    assert intake.value == 75000
    assert intake.practice_area.name == "General"
    assert intake.importance == 7  # clamped

    assistant = conversation.messages.get(role="assistant")
    assert "Updated value: 75000" in assistant.content
    assert "```update-intake" not in assistant.content


def test_update_block_rejects_bad_values(client, intake, mock_gemini, monkeypatch):
    original_status = intake.status
    monkeypatch.setattr(
        "apps.case.ai.gemini_client.send_to_gemini_streaming",
        lambda *a, **k: (
            update_block({"status": "Vaporized", "source": "Carrier Pigeon"}),
            10,
            5,
        ),
    )
    send(client, intake, "Mark it vaporized.")
    conversation = Conversation.objects.get()
    client.get(f"/case/ai/status/{conversation.id}/")

    intake.refresh_from_db()
    assert intake.status == original_status
    assistant = conversation.messages.get(role="assistant")
    assert "not recognized" in assistant.content


def test_update_block_invalid_json_left_alone(client, intake, monkeypatch):
    text = "```update-intake\nnot json\n```"
    monkeypatch.setattr(
        "apps.case.ai.gemini_client.send_to_gemini_streaming",
        lambda *a, **k: (text, 10, 5),
    )
    original_name = intake.name
    send(client, intake, "Update something.")
    conversation = Conversation.objects.get()
    client.get(f"/case/ai/status/{conversation.id}/")

    intake.refresh_from_db()
    assert intake.name == original_name
    assert "```update-intake" in conversation.messages.get(role="assistant").content
