"""Tests for draft-link views and the chat surface integration."""

import pytest

from apps.drafts import services
from apps.drafts.models import DraftLink

pytestmark = pytest.mark.django_db


def test_picker_lists_files(client, conversation, monkeypatch):
    monkeypatch.setattr("apps.drafts.views.google.check_credentials", lambda: True)
    monkeypatch.setattr(
        services,
        "list_matter_odt_files",
        lambda m: [
            {"id": "f1", "name": "motion.odt", "path": "Pleadings/", "modifiedTime": ""}
        ],
    )
    response = client.get(f"/case/ai/conversations/{conversation.id}/draft/picker/")
    assert response.status_code == 200
    assert b"Pleadings/" in response.content
    assert b"motion.odt" in response.content
    assert b"companion" in response.content.lower()


def test_picker_degrades_without_drive(client, conversation, monkeypatch):
    monkeypatch.setattr("apps.drafts.views.google.check_credentials", lambda: False)
    response = client.get(f"/case/ai/conversations/{conversation.id}/draft/picker/")
    assert response.status_code == 200
    assert b"Connect Google Drive" in response.content


def test_link_and_unlink_cycle(client, conversation, monkeypatch):
    monkeypatch.setattr(
        services, "_fetch_drive_text", lambda fid: ("motion.odt", "TEXT")
    )
    response = client.post(
        f"/case/ai/conversations/{conversation.id}/draft/link/", {"file": "f1"}
    )
    assert response.status_code == 200
    assert response["HX-Trigger"] == "draftLinkChanged"
    assert b"motion.odt" in response.content
    assert DraftLink.objects.filter(conversation=conversation).exists()

    response = client.post(f"/case/ai/conversations/{conversation.id}/draft/unlink/")
    assert response.status_code == 200
    assert not DraftLink.objects.filter(conversation=conversation).exists()
    # Chip returns to the link button.
    assert b"draft/picker" in response.content


def test_link_requires_file_param(client, conversation):
    response = client.post(f"/case/ai/conversations/{conversation.id}/draft/link/")
    assert response.status_code == 400


def test_link_drive_failure_reported(client, conversation, monkeypatch):
    def boom(fid):
        raise services.DraftError("Drive is down")

    monkeypatch.setattr(services, "_fetch_drive_text", boom)
    response = client.post(
        f"/case/ai/conversations/{conversation.id}/draft/link/", {"file": "f1"}
    )
    assert response.status_code == 502


def test_chip_endpoint(client, link):
    response = client.get(f"/case/ai/conversations/{link.conversation_id}/draft/chip/")
    assert response.status_code == 200
    assert b"motion.odt" in response.content


def test_conversation_list_shows_draft_badge(client, link, matter):
    response = client.get(f"/case/{matter.id}/ai/")
    assert response.status_code == 200
    assert b"ai-draft-badge" in response.content


def test_standalone_chat_shows_chip(client, link, matter):
    response = client.get(f"/case/ai/conversations/{link.conversation_id}/view/")
    assert response.status_code == 200
    assert b"draftChip" in response.content
    assert b"motion.odt" in response.content


def test_companion_setup_modal(client):
    response = client.get("/case/drafts/companion/setup/")
    assert response.status_code == 200
    assert b"kosmos-companion.oxt" in response.content


def test_drafts_tab_is_gone(client, matter):
    assert client.get(f"/case/{matter.id}/drafts/").status_code == 404


def test_new_chat_window_shows_paperclip_before_first_message(client, matter):
    response = client.get(f"/case/{matter.id}/ai/conversations/new/")
    assert response.status_code == 200
    assert b"linkDraftForNewChat" in response.content
    assert b"icon-file-plus-2" in response.content


def test_create_conversation_endpoint(client, matter):
    import json

    from apps.case.ai.models import Conversation

    response = client.post(
        f"/case/{matter.id}/ai/conversations/create/",
        {"llm": "gemini-pro-latest", "kind": "classic", "title": "Draft chat"},
    )
    assert response.status_code == 200
    conv = Conversation.objects.get(id=json.loads(response.content)["id"])
    assert conv.matter == matter
    assert conv.title == "Draft chat"
    assert conv.kind == "classic"
