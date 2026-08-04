"""Session lifecycle against real LibreOffice where required."""

import pytest

from apps.drafts import services
from apps.drafts.models import DraftSession
from apps.drive import redline
from apps.drive.redline import RedlineEdit, RedlineError

needs_uno = pytest.mark.skipif(
    not redline.is_available(),
    reason="LibreOffice + python3-uno required "
    "(apt-get install libreoffice-writer-nogui python3-uno)",
)

pytestmark = pytest.mark.django_db


def _sample_odt_bytes():
    import tempfile
    from pathlib import Path

    from apps.drive.tests.test_redline import _sample_draft

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "motion.odt"
        _sample_draft(path)
        return path.read_bytes()


class _FakeFiles:
    def __init__(self, meta):
        self._meta = meta

    def get(self, fileId, fields=None, supportsAllDrives=None):
        class _Call:
            def __init__(self, meta):
                self._meta = meta

            def execute(self):
                return self._meta

        return _Call(self._meta)


class _FakeService:
    def __init__(self, meta):
        self._files = _FakeFiles(meta)

    def files(self):
        return self._files


@pytest.fixture
def fake_drive_file(monkeypatch):
    """Patch the google layer so create_session sees one Drive ODT."""
    content = _sample_odt_bytes()
    meta = {
        "id": "file1",
        "name": "motion.odt",
        "mimeType": "application/vnd.oasis.opendocument.text",
        "modifiedTime": "2026-08-01T12:00:00.000Z",
    }
    monkeypatch.setattr("apps.drafts.services.google.check_credentials", lambda: True)
    monkeypatch.setattr(
        "apps.drafts.services.google.build_service", lambda: _FakeService(meta)
    )
    monkeypatch.setattr("apps.drafts.services.google._download", lambda svc, m: content)
    return meta


@needs_uno
class TestLifecycle:
    def test_create_session_builds_version_zero(self, matter, user, fake_drive_file):
        session = services.create_session(matter, "file1", user)

        assert session.status == "drafting"
        assert session.drive_modified == "2026-08-01T12:00:00.000Z"
        assert session.conversation is not None
        version = session.current_version
        assert version.seq == 0
        assert "MOTION TO DISMISS" in version.facsimile
        with version.pdf_file.open("rb") as fh:
            assert fh.read(5) == b"%PDF-"

    def test_edit_round_publish_and_purge(self, matter, user, fake_drive_file):
        session = services.create_session(matter, "file1", user)

        v1 = services.apply_edit_round(
            session,
            [RedlineEdit(old="upon which relief can be granted", new="whatsoever")],
        )
        assert v1.seq == 1
        assert "whatsoever" in v1.facsimile
        assert v1.edits[0]["old"] == "upon which relief can be granted"

        v0 = session.versions.get(seq=0)
        assert v0.odt_file and v1.odt_file

        final = services.publish_session(session)
        session.refresh_from_db()
        assert final.pk == v1.pk
        assert session.status == "published"
        assert session.published_at is not None

        v0.refresh_from_db()
        v1.refresh_from_db()
        assert not v0.odt_file and not v0.pdf_file  # purged
        assert v1.odt_file and v1.pdf_file  # final kept
        assert v0.facsimile  # paper trail survives

        with pytest.raises(services.DraftError):
            services.apply_edit_round(session, [RedlineEdit(old="a", new="b")])
        with pytest.raises(services.DraftError):
            services.publish_session(session)

    def test_failed_round_creates_no_version(self, matter, user, fake_drive_file):
        session = services.create_session(matter, "file1", user)
        with pytest.raises(RedlineError):
            services.apply_edit_round(
                session, [RedlineEdit(old="phrase that appears nowhere", new="x")]
            )
        assert session.versions.count() == 1


def test_abandon_purges_everything(session):
    services.abandon_session(session)
    session.refresh_from_db()
    version = session.versions.get(seq=0)
    assert session.status == "abandoned"
    assert not version.odt_file and not version.pdf_file
    assert version.facsimile

    with pytest.raises(services.DraftError):
        services.abandon_session(
            DraftSession(status="published", matter=session.matter)
        )


def test_create_session_rejects_non_odt(matter, user, monkeypatch):
    meta = {"id": "f2", "name": "notes.docx", "modifiedTime": "x"}
    monkeypatch.setattr("apps.drafts.services.google.check_credentials", lambda: True)
    monkeypatch.setattr(
        "apps.drafts.services.google.build_service", lambda: _FakeService(meta)
    )
    monkeypatch.setattr("apps.drafts.services.google._download", lambda svc, m: b"")
    with pytest.raises(services.DraftError, match="only support .odt"):
        services.create_session(matter, "f2", user)
