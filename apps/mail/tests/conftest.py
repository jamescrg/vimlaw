import base64

import httplib2
import pytest
from django.test import Client
from googleapiclient.errors import HttpError

from apps.accounts.models import CustomUser
from apps.mail.models import GmailAccount
from apps.matters.models import Matter
from apps.settings.models import Firm


@pytest.fixture(autouse=True)
def company(db):
    return Firm.objects.create(name="Test Firm LLC")


@pytest.fixture
def user():
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
    # The label NAME is the sync contract; ids are per-mailbox.
    return Matter.objects.create(
        name="Smith v Jones",
        status="Open",
        gmail_label_name="Matters - Open/Smith",
    )


@pytest.fixture
def matter2(db):
    return Matter.objects.create(
        name="Doe v Roe",
        status="Open",
        gmail_label_name="Matters - Open/Doe",
    )


def http_error(status):
    resp = httplib2.Response({"status": status})
    resp.reason = "error"
    return HttpError(resp, b"{}")


def b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode()


def gmail_message(
    gmail_id,
    thread_id="thread-1",
    subject="Test subject",
    sender="Alice <alice@example.com>",
    to="Bob <bob@example.com>",
    body="Hello there",
    label_ids=("Label_1",),
    internal_ms=1753800000000,
    message_id=None,
):
    """A minimal single-part text/plain messages.get(format=full) response.

    ``message_id`` defaults to a per-gmail_id value; pass the same one for
    two gmail_ids to model one message held in two mailboxes.
    """
    return {
        "id": gmail_id,
        "threadId": thread_id,
        "labelIds": list(label_ids),
        "internalDate": str(internal_ms),
        "snippet": body[:100],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": sender},
                {"name": "To", "value": to},
                {"name": "Subject", "value": subject},
                {
                    "name": "Message-ID",
                    "value": message_id or f"<{gmail_id}@mail.example.com>",
                },
            ],
            "body": {"data": b64(body), "size": len(body)},
        },
    }


class _Call:
    def __init__(self, result):
        self._result = result

    def execute(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _Users:
    def __init__(self, service):
        self._service = service

    def getProfile(self, userId):
        return _Call(
            {
                "historyId": self._service.profile_history_id,
                "emailAddress": getattr(self._service, "address", ""),
            }
        )

    def labels(self):
        return _Labels(self._service)

    def messages(self):
        return _Messages(self._service)

    def history(self):
        return _History(self._service)


class _Labels:
    def __init__(self, service):
        self._service = service

    def list(self, userId):
        return _Call({"labels": self._service.labels})


class _Messages:
    def __init__(self, service):
        self._service = service

    def list(self, userId, labelIds, maxResults, pageToken=None):
        label_id = labelIds[0]
        ids = [
            m["id"]
            for m in self._service.messages.values()
            if label_id in m.get("labelIds", [])
        ]
        return _Call({"messages": [{"id": i} for i in ids]})

    def get(self, userId, id, format, metadataHeaders=None):
        msg = self._service.messages.get(id)
        if msg is None:
            return _Call(http_error(404))
        return _Call(msg)

    def attachments(self):
        return _Attachments(self._service)


class _Attachments:
    def __init__(self, service):
        self._service = service

    def get(self, userId, messageId, id):
        data = self._service.attachment_data.get(id)
        if data is None:
            return _Call(http_error(404))
        return _Call({"data": base64.urlsafe_b64encode(data).decode()})


class _History:
    def __init__(self, service):
        self._service = service

    def list(self, userId, startHistoryId, maxResults, pageToken=None):
        if isinstance(self._service.history, Exception):
            return _Call(self._service.history)
        return _Call(
            {
                "history": self._service.history,
                "historyId": self._service.profile_history_id,
            }
        )


class FakeGmailService:
    """Canned Gmail API: labels, messages keyed by id, one history page."""

    def __init__(self, labels=None, messages=None, history=None, history_id="2000"):
        # attachment_id -> raw bytes, served by attachments().get.
        self.attachment_data = {}
        self.labels = labels or [
            {"id": "Label_1", "name": "Matters - Open/Smith", "type": "user"},
            {"id": "Label_2", "name": "Matters - Open/Doe", "type": "user"},
            {"id": "Label_8", "name": "Admin/Billing", "type": "user"},
            {"id": "INBOX", "name": "INBOX", "type": "system"},
        ]
        self.messages = {m["id"]: m for m in (messages or [])}
        self.history = history or []
        self.profile_history_id = history_id

    def users(self):
        return _Users(self)


@pytest.fixture
def fake_gmail(monkeypatch, user):
    """Install a FakeGmailService bound to ``user``'s GmailAccount.

    ``build_service`` is patched to a per-account registry, so tests add a
    second mailbox with ``fake_gmail.connect(other_user, "addr", service2)``
    (a fresh FakeGmailService by default). check_credentials() is real —
    it just sees the GmailAccount rows.
    """
    service = FakeGmailService()
    service.address = "primary@example.com"
    service.account = GmailAccount.objects.create(
        user=user, address=service.address, token='{"token": "t"}'
    )
    registry = {service.account.pk: service}
    monkeypatch.setattr(
        "apps.mail.google.build_service",
        lambda account: registry.get(getattr(account, "pk", None), False),
    )

    def connect(owner, address, other_service=None):
        other_service = other_service or FakeGmailService()
        other_service.address = address
        other_service.account = GmailAccount.objects.create(
            user=owner, address=address, token='{"token": "t"}'
        )
        registry[other_service.account.pk] = other_service
        return other_service

    service.connect = connect
    return service
