import hashlib
import hmac
import json
import time

import pytest
from django.test import Client
from django.utils import timezone

from apps.intakes.inbound import process_inbound_email
from apps.intakes.models import InboundEmail, Intake, Note
from apps.matters.models import PracticeArea

pytestmark = pytest.mark.django_db

SIGNING_KEY = "test-key"


@pytest.fixture(autouse=True)
def _signing_key(settings):
    """Pin a known key regardless of the developer's .env; the
    unenforced-mode test blanks it explicitly."""
    settings.MAILGUN_WEBHOOK_SIGNING_KEY = SIGNING_KEY


@pytest.fixture(autouse=True)
def _inline_tasks(monkeypatch):
    """Run the worker task synchronously instead of queueing it."""
    import django_q.tasks

    monkeypatch.setattr(
        django_q.tasks,
        "async_task",
        lambda func, *args, **kwargs: process_inbound_email(*args),
    )


@pytest.fixture
def mock_ai(monkeypatch):
    """Replace the Gemini call; pass a dict (JSON-encoded for you) or a raw
    string to simulate malformed output."""

    def _set(payload):
        text = payload if isinstance(payload, str) else json.dumps(payload)
        monkeypatch.setattr(
            "apps.case.ai.gemini_client.send_to_gemini",
            lambda *args, **kwargs: (text, 10, 5),
        )

    return _set


EXTRACTION = {
    "kind": "email",
    "name": "Jane Roe",
    "phone": "(404) 555-0100",
    "email": "jane@example.com",
    "address": "12 Oak St, Atlanta, GA",
    "disputed_property": "14 Oak St, Atlanta, GA",
    "value": 250000,
    "practice_area": "General",
    "source": "Internet",
    "summary": "Jane Roe has a boundary dispute with her neighbor.",
}


def signature_fields(key=SIGNING_KEY, timestamp=None):
    timestamp = str(int(time.time())) if timestamp is None else timestamp
    token = "tok-abc123"
    signature = hmac.new(
        key.encode(), f"{timestamp}{token}".encode(), hashlib.sha256
    ).hexdigest()
    return {"timestamp": timestamp, "token": token, "signature": signature}


def post_inbound(overrides=None, **sig_kwargs):
    # Public ingress: no login, csrf exempt, form-encoded like Mailgun posts
    data = {
        "from": "Ollie <testuser@example.com>",
        "recipient": "intake@mail.example.com",
        "subject": "FW: Boundary dispute",
        "body-plain": "Hi, my neighbor built a fence over my property line.",
        "Message-Id": "<unique-id@mail.example.com>",
    }
    data.update(signature_fields(**sig_kwargs))
    if overrides:
        data.update(overrides)
    return Client().post("/api/inbound-email/", data=data)


def test_valid_signature_accepted(user, mock_ai):
    mock_ai(EXTRACTION)
    response = post_inbound()
    assert response.status_code == 200
    inbound = InboundEmail.objects.get()
    assert inbound.sender == "testuser@example.com"
    assert inbound.message_id == "unique-id@mail.example.com"
    assert inbound.status == "processed"


def test_invalid_signature_rejected(user):
    response = post_inbound({"signature": "0" * 64})
    assert response.status_code == 403
    assert InboundEmail.objects.count() == 0


def test_stale_timestamp_rejected(user):
    response = post_inbound(timestamp=str(int(time.time()) - 3600))
    assert response.status_code == 403
    assert InboundEmail.objects.count() == 0


def test_blank_key_unenforced(user, mock_ai, settings):
    settings.MAILGUN_WEBHOOK_SIGNING_KEY = ""
    mock_ai(EXTRACTION)
    response = post_inbound({"signature": "", "timestamp": "", "token": ""})
    assert response.status_code == 200
    assert InboundEmail.objects.count() == 1


def test_non_intake_recipient_dropped(user, mock_ai):
    # The shared route also relays billing replies to the webhook
    mock_ai(EXTRACTION)
    response = post_inbound({"recipient": "billing@mail.example.com"})
    assert response.status_code == 200
    assert InboundEmail.objects.count() == 0
    assert Intake.objects.count() == 0


def test_unknown_sender_dropped(user, mock_ai):
    mock_ai(EXTRACTION)
    response = post_inbound({"from": "Spammer <spam@example.net>"})
    assert response.status_code == 200
    assert InboundEmail.objects.count() == 0
    assert Intake.objects.count() == 0


def test_duplicate_message_id_is_noop(user, mock_ai):
    mock_ai(EXTRACTION)
    assert post_inbound().status_code == 200
    assert post_inbound().status_code == 200
    assert InboundEmail.objects.count() == 1
    assert Intake.objects.count() == 1


def test_happy_path_creates_intake_and_note(user, mock_ai):
    mock_ai(EXTRACTION)
    post_inbound()

    intake = Intake.objects.get()
    assert intake.name == "Jane Roe"
    assert intake.phone == "4045550100"
    assert intake.email == "jane@example.com"
    assert intake.address == "12 Oak St, Atlanta, GA"
    assert intake.disputed_property == "14 Oak St, Atlanta, GA"
    assert intake.value == 250000
    # "General" is seeded by the matters migrations; match by name since
    # the fixture row would be a duplicate
    assert intake.practice_area.name == "General"
    assert intake.source == "Internet"
    assert intake.status == "Open"
    assert intake.date == timezone.localdate()

    note = Note.objects.get()
    assert note.intake_id == intake.id
    assert note.user == user
    assert note.type == "Email In"
    assert "AI summary" in note.details
    assert "boundary dispute with her neighbor" in note.details
    assert "fence over my property line" in note.details

    inbound = InboundEmail.objects.get()
    assert inbound.intake_id == intake.id
    assert inbound.status == "processed"
    assert inbound.error == ""


def test_voicemail_kind_maps_to_vm_note(user, mock_ai):
    mock_ai({**EXTRACTION, "kind": "voicemail"})
    post_inbound()
    assert Note.objects.get().type == "VM In"


def test_practice_area_matches_case_insensitively(user, mock_ai):
    mock_ai({**EXTRACTION, "practice_area": "gEnErAl"})
    post_inbound()
    assert Intake.objects.get().practice_area.name == "General"


def test_unknown_or_inactive_practice_area_ignored(user, mock_ai):
    PracticeArea.objects.create(name="Dormant", is_active=False)
    mock_ai({**EXTRACTION, "practice_area": "Dormant"})
    post_inbound()
    assert Intake.objects.get().practice_area is None


def test_malformed_ai_response_still_creates_intake(user, mock_ai):
    mock_ai("I could not parse this message, sorry!")
    post_inbound()

    intake = Intake.objects.get()
    assert intake.name == "FW: Boundary dispute"
    assert intake.status == "Open"
    assert intake.source == "Unknown"

    note = Note.objects.get()
    assert note.type == "Email In"
    assert "fence over my property line" in note.details

    inbound = InboundEmail.objects.get()
    assert inbound.status == "failed"
    assert inbound.error
    assert inbound.intake_id == intake.id


def test_missing_name_falls_back_to_phone(user, mock_ai):
    mock_ai({**EXTRACTION, "name": None})
    post_inbound()
    assert Intake.objects.get().name == "Unknown caller 4045550100"


def test_invalid_source_and_phone_handled(user, mock_ai):
    mock_ai({**EXTRACTION, "source": "Carrier Pigeon", "phone": "not a number"})
    post_inbound()
    intake = Intake.objects.get()
    assert intake.source == "Unknown"
    assert intake.phone == "not a number"
