"""Tests for the LibreOffice companion: token API and oxt build."""

import base64
import io
import json
import zipfile

import pytest
from django.utils import timezone

from apps.drafts import companion
from apps.drafts.models import CompanionRound, CompanionToken

pytestmark = pytest.mark.django_db


@pytest.fixture
def token(user):
    return CompanionToken.for_user(user)


@pytest.fixture
def api(token):
    """The logged-out API caller: auth is the token header, not the cookie."""
    from django.test import Client

    api = Client()
    api.defaults["HTTP_X_KOSMOS_TOKEN"] = token.key
    return api


def test_api_requires_valid_token(link):
    from django.test import Client

    anon = Client()
    assert anon.get("/case/drafts/companion/api/sessions/").status_code == 401
    anon.defaults["HTTP_X_KOSMOS_TOKEN"] = "wrong"
    assert anon.get("/case/drafts/companion/api/sessions/").status_code == 401


def test_token_is_stable_per_user(user):
    assert CompanionToken.for_user(user).key == CompanionToken.for_user(user).key


def test_sessions_lists_own_links(api, link, matter, user):
    data = json.loads(api.get("/case/drafts/companion/api/sessions/").content)
    assert [s["name"] for s in data["sessions"]] == ["motion.odt"]
    assert data["sessions"][0]["matter"] == "Smith v Jones"
    assert data["sessions"][0]["id"] == link.id


def test_sessions_excludes_other_users_links(api, link):
    link.conversation.user = None
    link.conversation.save()
    data = json.loads(api.get("/case/drafts/companion/api/sessions/").content)
    assert data["sessions"] == []


def test_hello_registers_and_stores_document(api, link, monkeypatch):
    monkeypatch.setattr(
        companion.convert, "to_markdown", lambda b, ext: "MD " + b.decode()
    )
    payload = {"odt_b64": base64.b64encode(b"odt-bytes").decode()}
    response = api.post(
        f"/case/drafts/companion/api/{link.id}/hello/",
        json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 200
    link.refresh_from_db()
    assert link.companion_active
    assert link.doc_text == "MD odt-bytes"


def test_unlinked_draft_answers_404(api, link):
    link_id = link.id
    link.delete()
    assert api.get(f"/case/drafts/companion/api/{link_id}/ops/").status_code == 404


def test_ops_delivers_each_round_once(api, link):
    round_ = CompanionRound.objects.create(
        link=link, edits=[{"op": "replace", "old": "a", "new": "b"}]
    )
    data = json.loads(api.get(f"/case/drafts/companion/api/{link.id}/ops/").content)
    assert data["round"]["id"] == round_.id
    assert data["round"]["edits"][0]["old"] == "a"
    data = json.loads(api.get(f"/case/drafts/companion/api/{link.id}/ops/").content)
    assert data["round"] is None
    link.refresh_from_db()
    assert link.companion_active


def test_result_marks_applied(api, link, monkeypatch):
    monkeypatch.setattr(companion.convert, "to_markdown", lambda b, ext: "AFTER")
    round_ = CompanionRound.objects.create(link=link, edits=[])
    payload = {
        "ok": True,
        "results": [{"op": "replace", "replacements": 1}],
        "odt_b64": base64.b64encode(b"x").decode(),
    }
    response = api.post(
        f"/case/drafts/companion/api/{link.id}/rounds/{round_.id}/",
        json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 200
    round_.refresh_from_db()
    link.refresh_from_db()
    assert round_.status == "applied"
    assert round_.result == [{"op": "replace", "replacements": 1}]
    assert link.doc_text == "AFTER"


def test_result_marks_failed_with_index(api, link):
    round_ = CompanionRound.objects.create(link=link, edits=[])
    payload = {"ok": False, "error": "text not found", "edit_index": 2}
    api.post(
        f"/case/drafts/companion/api/{link.id}/rounds/{round_.id}/",
        json.dumps(payload),
        content_type="application/json",
    )
    round_.refresh_from_db()
    assert round_.status == "failed"
    assert round_.error == "text not found"
    assert round_.edit_index == 2


def test_companion_not_active_after_window(link):
    from datetime import timedelta

    link.companion_seen = timezone.now() - timedelta(seconds=60)
    link.save()
    assert not link.companion_active


def test_oxt_download_is_personalized_zip(client, user, settings):
    settings.PUBLIC_BASE_URL = "https://kosmos.example"
    response = client.get("/case/drafts/companion/kosmos-companion.oxt")
    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))
    names = archive.namelist()
    assert "META-INF/manifest.xml" in names
    assert "description.xml" in names
    assert "Addons.xcu" in names
    assert "kosmos_companion.py" in names
    config = json.loads(archive.read("config.json"))
    assert config["server"] == "https://kosmos.example"
    assert config["token"] == CompanionToken.for_user(user).key


@pytest.fixture
def sibling(link, matter, user):
    """A second conversation linking the same Drive file."""
    from apps.case.ai.models import Conversation
    from apps.drafts.models import DraftLink

    conv = Conversation.objects.create(
        matter=matter, title="Second chat", llm="gemini-pro-latest", user=user
    )
    return DraftLink.objects.create(
        conversation=conv, drive_file_id="file1", name="motion.odt"
    )


def test_connection_is_shared_across_sibling_links(api, link, sibling):
    """Polling one link makes the whole document count as connected."""
    api.get(f"/case/drafts/companion/api/{link.id}/ops/")
    sibling.refresh_from_db()
    assert sibling.companion_active


def test_ops_serves_sibling_rounds(api, link, sibling):
    """A round queued by the new conversation reaches the old connection."""
    round_ = CompanionRound.objects.create(
        link=sibling, edits=[{"op": "replace", "old": "a", "new": "b"}]
    )
    data = json.loads(api.get(f"/case/drafts/companion/api/{link.id}/ops/").content)
    assert data["round"]["id"] == round_.id


def test_result_accepts_sibling_round(api, link, sibling):
    round_ = CompanionRound.objects.create(link=sibling, edits=[])
    response = api.post(
        f"/case/drafts/companion/api/{link.id}/rounds/{round_.id}/",
        json.dumps({"ok": True, "results": []}),
        content_type="application/json",
    )
    assert response.status_code == 200
    round_.refresh_from_db()
    assert round_.status == "applied"


def test_document_push_updates_all_siblings(api, link, sibling, monkeypatch):
    monkeypatch.setattr(companion.convert, "to_markdown", lambda b, ext: "SHARED")
    payload = {"odt_b64": base64.b64encode(b"x").decode()}
    api.post(
        f"/case/drafts/companion/api/{link.id}/hello/",
        json.dumps(payload),
        content_type="application/json",
    )
    sibling.refresh_from_db()
    assert sibling.doc_text == "SHARED"


def test_other_file_links_do_not_share(api, link, matter, user):
    from apps.case.ai.models import Conversation
    from apps.drafts.models import DraftLink

    conv = Conversation.objects.create(
        matter=matter, title="Other doc chat", llm="gemini-pro-latest", user=user
    )
    other = DraftLink.objects.create(
        conversation=conv, drive_file_id="file-OTHER", name="brief.odt"
    )
    api.get(f"/case/drafts/companion/api/{link.id}/ops/")
    other.refresh_from_db()
    assert not other.companion_active
