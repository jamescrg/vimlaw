import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding

FOLDER_MIME = "application/vnd.google-apps.folder"
PDF_MIME = "application/pdf"


class _Call:
    def __init__(self, result):
        self._result = result

    def execute(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _public(meta):
    """The fields FILE_FIELDS requests, as list/get responses carry them."""
    return {
        key: meta[key]
        for key in (
            "id",
            "name",
            "mimeType",
            "parents",
            "trashed",
            "modifiedTime",
            "createdTime",
            "size",
        )
        if key in meta
    }


class _Files:
    def __init__(self, service):
        self._service = service

    def list(self, q="", fields=None, pageToken=None, pageSize=None, **kwargs):
        store = self._service.files_by_id.values()
        if "in parents" in q:
            parent = q.split("'")[1]
            found = [
                m
                for m in store
                if parent in (m.get("parents") or []) and not m.get("trashed")
            ]
        else:
            # Root-folder lookup by name.
            name = q.split("'")[1]
            found = [
                m
                for m in store
                if m["name"] == name
                and m["mimeType"] == FOLDER_MIME
                and not m.get("trashed")
            ]
        return _Call({"files": [_public(m) for m in found]})

    def get(self, fileId, fields=None, supportsAllDrives=None):
        meta = self._service.files_by_id.get(fileId)
        if meta is None:
            from apps.mail.tests.conftest import http_error

            return _Call(http_error(404))
        return _Call(_public(meta))


class _Changes:
    def __init__(self, service):
        self._service = service

    def list(
        self, pageToken=None, includeRemoved=None, fields=None, pageSize=None, **kw
    ):
        if isinstance(self._service.change_feed, Exception):
            return _Call(self._service.change_feed)
        return _Call(
            {
                "changes": self._service.change_feed,
                "newStartPageToken": self._service.start_page_token,
            }
        )

    def getStartPageToken(self, **kwargs):
        return _Call({"startPageToken": self._service.start_page_token})


class FakeDriveService:
    """In-memory Drive: a file tree keyed by id plus a one-page changes feed.

    Bytes are served by the monkeypatched google._download (from the meta's
    ``content``), so get_media/export_media are never exercised.
    """

    def __init__(self):
        self.files_by_id = {}
        self.change_feed = []
        self.start_page_token = "100"

    def add_folder(self, fid, name, parent=None):
        self.files_by_id[fid] = {
            "id": fid,
            "name": name,
            "mimeType": FOLDER_MIME,
            "parents": [parent] if parent else [],
            "trashed": False,
        }
        return self.files_by_id[fid]

    def add_file(
        self,
        fid,
        name,
        parent,
        mime=PDF_MIME,
        modified="2026-01-15T12:00:00.000Z",
        created="2026-01-10T12:00:00.000Z",
        content=b"%PDF-1.4 fake",
    ):
        self.files_by_id[fid] = {
            "id": fid,
            "name": name,
            "mimeType": mime,
            "parents": [parent],
            "trashed": False,
            "modifiedTime": modified,
            "createdTime": created,
            "size": str(len(content)),
            "content": content,
        }
        return self.files_by_id[fid]

    def change_for(self, fid, removed=False):
        """A changes-feed entry for one file, as changes().list returns it."""
        if removed:
            return {"fileId": fid, "removed": True}
        return {"fileId": fid, "removed": False, "file": _public(self.files_by_id[fid])}

    def files(self):
        return _Files(self)

    def changes(self):
        return _Changes(self)


@pytest.fixture
def user(db):
    user = CustomUser.objects.create(
        username="testuser", email="test@example.com", user_rate=100
    )
    user.set_password("testpass123")
    user.save()
    return user


@pytest.fixture
def client(user):
    client = Client()
    client.login(username="testuser", password="testpass123")
    client.get("/dash/")  # Set daily dash session to avoid redirect
    return client


@pytest.fixture
def matter(db):
    return Matter.objects.create(
        name="Smith v Jones", status="Open", drive_folder="Smith v. Jones"
    )


@pytest.fixture
def proceeding(matter):
    return Proceeding.objects.create(
        matter=matter,
        nickname="Main",
        forum="District Court",
        case_number="CV-2026-1",
        primary=True,
        drive_folder="CA-2 Record",
    )


@pytest.fixture
def fake_drive(monkeypatch, settings, db):
    """Install a FakeDriveService with the standard tree:

    Matters - Open/                      (root1)
      Smith v. Jones/                    (mf1)
        Notes/                           (nf1)
        CA-2 Record/                     (rf1)
    """
    settings.DRIVE_NOTES_ROOT = "Matters - Open"
    settings.DRIVE_SHARED_DRIVE_ID = ""
    settings.DRIVE_NOTES_DEBUG_DIR = ""

    service = FakeDriveService()
    service.add_folder("root1", "Matters - Open")
    service.add_folder("mf1", "Smith v. Jones", parent="root1")
    service.add_folder("nf1", "Notes", parent="mf1")
    service.add_folder("rf1", "CA-2 Record", parent="mf1")

    monkeypatch.setattr("apps.drive.google.build_service", lambda: service)
    monkeypatch.setattr("apps.drive.google.check_credentials", lambda: True)
    monkeypatch.setattr(
        "apps.drive.google._download",
        lambda svc, meta: svc.files_by_id[meta["id"]].get("content", b""),
    )

    # OCR queueing is inert; record the queued document ids.
    service.ocr_queued = []
    monkeypatch.setattr(
        "apps.drive.records._queue_ocr",
        lambda doc_id: service.ocr_queued.append(doc_id),
    )
    return service
