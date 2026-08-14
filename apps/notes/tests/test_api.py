"""Tests for the notes API's one write path (Claude Desktop MCP): the
toggle-gated append/replace endpoint. The read surface and auth are
covered by TestNotesApi in test_views.py."""

import json
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.drafts.models import CompanionToken

pytestmark = pytest.mark.django_db


@pytest.fixture
def api(user):
    return Client(HTTP_X_KOSMOS_TOKEN=CompanionToken.for_user(user).key)


@pytest.fixture
def restricted_api():
    """Token client for a non-admin user with no matter memberships."""
    outsider = CustomUser.objects.create(
        username="outsider", email="outsider@example.com", perm_all_matters=False
    )
    return Client(HTTP_X_KOSMOS_TOKEN=CompanionToken.for_user(outsider).key)


def grant(note, hours=24):
    note.ai_write_until = timezone.now() + timedelta(hours=hours)
    note.save(update_fields=["ai_write_until"])


def post_json(api, url, payload):
    return api.post(url, json.dumps(payload), content_type="application/json")


class TestNoteWrite:
    def url(self, note):
        return f"/notes/api/notes/{note.id}/write/"

    def test_no_grant_is_403_with_toggle_guidance(self, api, note):
        response = post_json(api, self.url(note), {"content": "new line"})
        assert response.status_code == 403
        assert "Kosmos editor" in response.json()["error"]
        note.refresh_from_db()
        assert note.content == "This is test content for the note."

    def test_expired_grant_is_403(self, api, note):
        grant(note, hours=-1)
        response = post_json(api, self.url(note), {"content": "new line"})
        assert response.status_code == 403

    def test_append(self, api, note):
        grant(note)
        old_updated = note.updated_at
        history_before = note.history.count()
        response = post_json(api, self.url(note), {"content": "Appended line."})
        assert response.status_code == 200
        assert response.json()["message"].startswith("Appended to note:")
        note.refresh_from_db()
        assert note.content == "This is test content for the note.\n\nAppended line."
        assert note.updated_at > old_updated
        assert note.history.count() == history_before + 1

    def test_replace(self, api, note):
        grant(note)
        response = post_json(
            api, self.url(note), {"content": "Fresh content.", "mode": "replace"}
        )
        assert response.status_code == 200
        assert response.json()["message"].startswith("Rewrote note:")
        note.refresh_from_db()
        assert note.content == "Fresh content."

    def test_unknown_mode_falls_back_to_append(self, api, note):
        grant(note)
        response = post_json(
            api, self.url(note), {"content": "More.", "mode": "obliterate"}
        )
        assert response.status_code == 200
        note.refresh_from_db()
        assert note.content.endswith("\n\nMore.")

    def test_empty_content_is_400(self, api, note):
        grant(note)
        response = post_json(api, self.url(note), {"content": "   "})
        assert response.status_code == 400

    def test_bad_json_is_400(self, api, note):
        grant(note)
        response = api.post(self.url(note), "not json", content_type="application/json")
        assert response.status_code == 400

    def test_denied_matter_note_is_404_even_with_grant(self, restricted_api, note):
        grant(note)
        response = post_json(restricted_api, self.url(note), {"content": "x"})
        assert response.status_code == 404

    def test_get_is_rejected(self, api, note):
        assert api.get(self.url(note)).status_code == 405
