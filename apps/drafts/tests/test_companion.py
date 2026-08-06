"""Tests for the LibreOffice companion: token API, chat routing, oxt build."""

import base64
import io
import json
import zipfile

import pytest
from django.utils import timezone

from apps.drafts import chat, companion
from apps.drafts.models import CompanionRound, CompanionToken

pytestmark = pytest.mark.django_db


@pytest.fixture
def token(user):
    return CompanionToken.for_user(user)


@pytest.fixture
def api(client, token):
    """The logged-out API caller: auth is the token header, not the cookie."""
    from django.test import Client

    api = Client()
    api.defaults["HTTP_X_KOSMOS_TOKEN"] = token.key
    return api


def _connect(session):
    session.companion_seen = timezone.now()
    session.companion_text = "LIVE TEXT"
    session.companion_text_at = timezone.now()
    session.save()


# ---- auth ----


def test_api_requires_valid_token(session):
    from django.test import Client

    anon = Client()
    assert anon.get("/case/drafts/companion/api/sessions/").status_code == 401
    anon.defaults["HTTP_X_KOSMOS_TOKEN"] = "wrong"
    assert anon.get("/case/drafts/companion/api/sessions/").status_code == 401


def test_token_is_stable_per_user(user):
    assert CompanionToken.for_user(user).key == CompanionToken.for_user(user).key


# ---- session listing and hello ----


def test_sessions_lists_only_active_own_sessions(api, session, matter):
    from apps.drafts.models import DraftSession

    DraftSession.objects.create(
        matter=matter, drive_file_id="f2", name="done.odt", status="published"
    )
    data = json.loads(api.get("/case/drafts/companion/api/sessions/").content)
    assert [s["name"] for s in data["sessions"]] == ["motion.odt"]
    assert data["sessions"][0]["matter"] == "Smith v Jones"


def test_hello_registers_and_stores_document(api, session, monkeypatch):
    monkeypatch.setattr(
        companion.convert, "to_markdown", lambda b, ext: "MD " + b.decode()
    )
    payload = {"odt_b64": base64.b64encode(b"odt-bytes").decode()}
    response = api.post(
        f"/case/drafts/companion/api/{session.id}/hello/",
        json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 200
    session.refresh_from_db()
    assert session.companion_active
    assert session.companion_text == "MD odt-bytes"
    assert session.companion_text_at is not None


def test_hello_refused_after_settling(api, session):
    session.status = "published"
    session.save()
    response = api.post(
        f"/case/drafts/companion/api/{session.id}/hello/",
        "{}",
        content_type="application/json",
    )
    assert response.status_code == 409


# ---- ops delivery and results ----


def test_ops_delivers_each_round_once(api, session):
    round_ = CompanionRound.objects.create(
        session=session, edits=[{"op": "replace", "old": "a", "new": "b"}]
    )
    data = json.loads(api.get(f"/case/drafts/companion/api/{session.id}/ops/").content)
    assert data["round"]["id"] == round_.id
    assert data["round"]["edits"][0]["old"] == "a"
    data = json.loads(api.get(f"/case/drafts/companion/api/{session.id}/ops/").content)
    assert data["round"] is None
    session.refresh_from_db()
    assert session.companion_active


def test_result_marks_applied(api, session, monkeypatch):
    monkeypatch.setattr(companion.convert, "to_markdown", lambda b, ext: "AFTER")
    round_ = CompanionRound.objects.create(session=session, edits=[])
    payload = {
        "ok": True,
        "results": [{"op": "replace", "replacements": 1}],
        "odt_b64": base64.b64encode(b"x").decode(),
    }
    response = api.post(
        f"/case/drafts/companion/api/{session.id}/rounds/{round_.id}/",
        json.dumps(payload),
        content_type="application/json",
    )
    assert response.status_code == 200
    round_.refresh_from_db()
    session.refresh_from_db()
    assert round_.status == "applied"
    assert round_.result == [{"op": "replace", "replacements": 1}]
    assert session.companion_text == "AFTER"


def test_result_marks_failed_with_index(api, session):
    round_ = CompanionRound.objects.create(session=session, edits=[])
    payload = {"ok": False, "error": "text not found", "edit_index": 2}
    api.post(
        f"/case/drafts/companion/api/{session.id}/rounds/{round_.id}/",
        json.dumps(payload),
        content_type="application/json",
    )
    round_.refresh_from_db()
    assert round_.status == "failed"
    assert round_.error == "text not found"
    assert round_.edit_index == 2


# ---- chat routing ----


BLOCK = '```draft-edits\n[{"old": "Some text.", "new": "Better text."}]\n```'


def _answer_on_sleep(monkeypatch, session, **round_fields):
    """Make the worker's wait loop see an answered round on its first tick.

    A real companion answers from another process; in tests that would need
    a second DB connection, which cannot see this test's transaction. Hooking
    the wait loop's sleep updates the round on the same connection instead.
    """

    def fake_sleep(seconds):
        round_ = CompanionRound.objects.get(session=session)
        for field, value in round_fields.items():
            setattr(round_, field, value)
        round_.save()

    monkeypatch.setattr(chat.time, "sleep", fake_sleep)


def test_edits_route_to_connected_companion(session, monkeypatch):
    _connect(session)
    _answer_on_sleep(
        monkeypatch,
        session,
        status="applied",
        result=[{"op": "replace", "replacements": 1}],
    )
    result = chat.apply_edit_blocks(f"Done.\n\n{BLOCK}", session)
    assert "in the open LibreOffice document" in result
    assert session.versions.count() == 1  # no headless version created


def test_companion_failure_reported(session, monkeypatch):
    _connect(session)
    _answer_on_sleep(
        monkeypatch, session, status="failed", error="text not found", edit_index=0
    )
    result = chat.apply_edit_blocks(f"Done.\n\n{BLOCK}", session)
    assert "were not applied" in result
    assert "edit 1: text not found" in result


def test_companion_timeout_expires_round(session, monkeypatch):
    _connect(session)
    monkeypatch.setattr(chat, "COMPANION_WAIT_SECONDS", 1)
    result = chat.apply_edit_blocks(f"Done.\n\n{BLOCK}", session)
    assert "did not respond in time" in result
    assert CompanionRound.objects.get(session=session).status == "expired"


def test_stale_companion_blocks_headless_apply(session, monkeypatch):
    """Newer live text + companion gone: refuse rather than edit stale copy."""
    session.companion_text = "LIVE TEXT"
    session.companion_text_at = timezone.now()  # newer than v0, but not seen
    session.save()

    def boom(*args, **kwargs):
        raise AssertionError("headless applier must not run")

    monkeypatch.setattr(chat.services, "apply_edit_round", boom)
    result = chat.apply_edit_blocks(f"Done.\n\n{BLOCK}", session)
    assert "no longer connected" in result


def test_prompt_prefers_fresh_companion_text(session, user):
    session.companion_text = "LIVE TEXT"
    session.companion_text_at = timezone.now()
    session.save()
    prompt = chat.build_system_prompt(session, user)
    assert "LIVE TEXT" in prompt
    assert "open LibreOffice window" in prompt


def test_prompt_uses_version_when_companion_text_older(session, user):
    session.companion_text = "LIVE TEXT"
    session.companion_text_at = timezone.now()
    session.save()
    # A newer server version (e.g. Sync from Drive) supersedes the push.
    from django.core.files.base import ContentFile

    from apps.drafts.models import DraftVersion

    version = DraftVersion(session=session, seq=1, facsimile="SERVER COPY", edits=[])
    version.odt_file.save("v1.odt", ContentFile(b"fake"), save=False)
    version.pdf_file.save("v1.pdf", ContentFile(b"fake"), save=False)
    version.save()
    prompt = chat.build_system_prompt(session, user)
    assert "SERVER COPY" in prompt
    assert "LIVE TEXT" not in prompt


def test_companion_not_active_after_window(session):
    from datetime import timedelta

    session.companion_seen = timezone.now() - timedelta(seconds=60)
    session.save()
    assert not session.companion_active


# ---- oxt build ----


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
