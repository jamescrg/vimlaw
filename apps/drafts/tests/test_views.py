"""Smoke tests for the Drafts tab and drafting window views."""

import pytest

from apps.drafts import services
from apps.drafts.models import DraftSession

pytestmark = pytest.mark.django_db


def test_drafts_tab_renders(client, matter, session, monkeypatch):
    # Pin Drive to unlinked regardless of the dev machine's real token file.
    monkeypatch.setattr("apps.drafts.views.google.check_credentials", lambda: False)
    response = client.get(f"/case/{matter.id}/drafts/")
    assert response.status_code == 200
    assert b"motion.odt" in response.content
    assert b"Connect Google Drive" in response.content


def test_picker_lists_files(client, matter, monkeypatch):
    monkeypatch.setattr(
        services,
        "list_matter_odt_files",
        lambda m: [
            {"id": "f1", "name": "motion.odt", "path": "Pleadings/", "modifiedTime": ""}
        ],
    )
    response = client.get(f"/case/{matter.id}/drafts/picker/")
    assert response.status_code == 200
    assert b"Pleadings/" in response.content
    assert b"motion.odt" in response.content


def test_start_resumes_existing_session(client, matter, session):
    response = client.get(f"/case/{matter.id}/drafts/start/?file=file1")
    assert response.status_code == 302
    assert response.url.endswith(f"/case/drafts/{session.id}/window/")
    assert DraftSession.objects.count() == 1


def test_start_requires_file_param(client, matter):
    assert client.get(f"/case/{matter.id}/drafts/start/").status_code == 400


def test_window_renders(client, session):
    response = client.get(f"/case/drafts/{session.id}/window/")
    assert response.status_code == 200
    assert b"draft-layout" in response.content
    assert b"draft-side" in response.content


def test_pane_short_circuits_on_have(client, session):
    url = f"/case/drafts/{session.id}/pane/"
    assert client.get(url).status_code == 200
    assert client.get(url + "?have=0").status_code == 204
    assert client.get(url + "?have=99").status_code == 200


def test_send_refused_after_settling(client, session):
    session.status = "published"
    session.save()
    response = client.post(
        f"/case/drafts/{session.id}/send/", {"message": "hi", "llm": "claude-opus"}
    )
    assert response.status_code == 409
    assert session.conversation.messages.count() == 0


def test_version_files_served_and_gone_when_purged(client, session):
    version = session.versions.get(seq=0)
    pdf = client.get(f"/case/drafts/version/{version.id}/pdf/")
    assert pdf.status_code == 200
    assert pdf["Content-Type"] == "application/pdf"

    odt = client.get(f"/case/drafts/version/{version.id}/odt/")
    assert odt.status_code == 200
    assert "redline v0" in odt["Content-Disposition"]

    services.abandon_session(session)
    assert client.get(f"/case/drafts/version/{version.id}/pdf/").status_code == 410
    assert client.get(f"/case/drafts/version/{version.id}/odt/").status_code == 410


def test_missing_blob_serves_410_not_500(client, session):
    """Rows can outlive blobs (dev's nightly media prune); degrade, not 500."""
    version = session.versions.get(seq=0)
    version.odt_file.name = "drafts/nowhere/v0.odt"
    version.pdf_file.name = "drafts/nowhere/v0.pdf"
    version.save(update_fields=["odt_file", "pdf_file"])
    assert client.get(f"/case/drafts/version/{version.id}/pdf/").status_code == 410
    assert client.get(f"/case/drafts/version/{version.id}/odt/").status_code == 410


def test_publish_endpoint(client, session):
    response = client.post(f"/case/drafts/{session.id}/publish/")
    assert response.status_code == 200
    assert response["HX-Trigger"] == "draftsChanged"
    session.refresh_from_db()
    assert session.status == "published"
    # No accept flag: the redlined current version stays final, no new one.
    assert session.versions.count() == 1


def test_publish_accept_flag_reaches_services(client, session, monkeypatch):
    calls = {}

    def fake_publish(sess, accept=False):
        calls["accept"] = accept
        sess.status = "published"
        sess.save()
        return sess.current_version

    monkeypatch.setattr("apps.drafts.views.services.publish_session", fake_publish)
    response = client.post(f"/case/drafts/{session.id}/publish/", {"accept": "1"})
    assert response.status_code == 200
    assert calls["accept"] is True
