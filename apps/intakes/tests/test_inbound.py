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
def _recipient(settings):
    """Pin the prod default; the dev box's .env says intakes-dev."""
    settings.INTAKE_INBOUND_RECIPIENT = "intakes"


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
    "disputed_property_address": "14 Oak St, Atlanta, GA",
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
        "recipient": "intakes@mail.example.com",
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


def test_recipient_local_part_is_configurable(user, mock_ai, settings):
    # Dev claims intakes-dev@ and must ignore prod's intakes@ mail
    settings.INTAKE_INBOUND_RECIPIENT = "intakes-dev"
    mock_ai(EXTRACTION)
    assert post_inbound().status_code == 200  # default recipient is intakes@
    assert InboundEmail.objects.count() == 0
    post_inbound({"recipient": "intakes-dev@mail.example.com"})
    assert Intake.objects.count() == 1


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
    # Kosmos authorship makes the new-note badge fire for the forwarder too
    assert note.user.username == "kosmos"
    assert not note.user.is_active
    assert note.type == "Email In"
    assert intake.importance == 4
    assert "AI summary" in note.details
    assert "boundary dispute with her neighbor" in note.details
    assert "fence over my property line" in note.details

    inbound = InboundEmail.objects.get()
    assert inbound.intake_id == intake.id
    assert inbound.status == "processed"
    assert inbound.error == ""


FORWARDED_BODY = (
    "See below, promising case.\n\n"
    "James Craig\nCraig Legal, LLC\n406-555-0199\n\n"
    "---------- Forwarded message ---------\n"
    "From: Jane Roe <jane@example.com>\n"
    "Date: Mon, Jul 27, 2026\n"
    "Subject: Fence dispute\n\n"
    "My neighbor built a fence over my property line."
)


def test_note_strips_forwarder_signature(user, mock_ai):
    mock_ai(EXTRACTION)
    post_inbound({"body-plain": FORWARDED_BODY})
    details = Note.objects.get().details
    assert "Craig Legal, LLC" not in details
    assert "promising case" not in details
    assert "Forwarded message" in details
    assert "From: Jane Roe" in details
    assert "fence over my property line" in details


def test_note_strips_outlook_original_message(user, mock_ai):
    mock_ai(EXTRACTION)
    body = (
        "Sig line\n\n-----Original Message-----\n"
        "From: Jane Roe\n\nFence dispute details."
    )
    post_inbound({"body-plain": body})
    details = Note.objects.get().details
    assert "Sig line" not in details
    assert "Fence dispute details." in details


def test_note_keeps_full_text_without_marker(user, mock_ai):
    # An unrecognized client's forward loses nothing
    mock_ai(EXTRACTION)
    post_inbound()
    assert "fence over my property line" in Note.objects.get().details


def test_ai_still_receives_full_text(user, monkeypatch):
    seen = {}

    def fake_gemini(system, messages, *args, **kwargs):
        seen["content"] = messages[0]["content"]
        return json.dumps(EXTRACTION), 10, 5

    monkeypatch.setattr("apps.case.ai.gemini_client.send_to_gemini", fake_gemini)
    post_inbound({"body-plain": FORWARDED_BODY})
    assert "promising case" in seen["content"]


def test_voicemail_kind_maps_to_vm_note(user, mock_ai):
    mock_ai({**EXTRACTION, "kind": "voicemail"})
    post_inbound()
    assert Note.objects.get().type == "VM In"


ZOOM_BODY = (
    "---------- Forwarded message ---------\n"
    "From: Zoom Phone <no-reply@zoom.us>\n\n"
    "You have a new voicemail!\n"
    "From: (404) 555-0100\nDuration: 0:45\n\n"
    "Voicemail transcription:\n"
    "Hi this is Jane Roe my neighbor put a fence on my land please call me\n\n"
    "Play voicemail: https://zoom.us/vm/abc123\nUnsubscribe | Help"
)


def test_voicemail_note_uses_extracted_transcript(user, mock_ai):
    transcript = "Hi this is Jane Roe my neighbor put a fence on my land please call me"
    mock_ai({**EXTRACTION, "kind": "voicemail", "transcript": transcript})
    post_inbound({"body-plain": ZOOM_BODY})
    details = Note.objects.get().details
    assert transcript in details
    assert "You have a new voicemail" not in details
    assert "Play voicemail" not in details


def test_voicemail_without_transcript_falls_back_to_body(user, mock_ai):
    mock_ai({**EXTRACTION, "kind": "voicemail", "transcript": None})
    post_inbound({"body-plain": ZOOM_BODY})
    assert "You have a new voicemail" in Note.objects.get().details


def test_email_kind_ignores_transcript_field(user, mock_ai):
    # A confused model must not replace a client's email text
    mock_ai({**EXTRACTION, "kind": "email", "transcript": "bogus"})
    post_inbound()
    details = Note.objects.get().details
    assert "bogus" not in details
    assert "fence over my property line" in details


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


def test_high_importance_seeds_assessment(user, mock_ai):
    mock_ai(
        {
            **EXTRACTION,
            "importance": 6,
            "importance_rationale": "Large disputed value and a clear claim.",
        }
    )
    post_inbound()
    intake = Intake.objects.get()
    assert intake.importance == 6
    assert intake.assessment == "Large disputed value and a clear claim."
    assert intake.assessed_at is not None
    assert Note.objects.count() == 1  # only the original message


def test_low_importance_seeds_assessment(user, mock_ai):
    mock_ai(
        {
            **EXTRACTION,
            "importance": 2,
            "importance_rationale": "Outside the firm's practice areas.",
        }
    )
    post_inbound()
    intake = Intake.objects.get()
    assert intake.importance == 2
    assert "Outside the firm" in intake.assessment


def test_null_importance_keeps_default_without_assessment(user, mock_ai):
    mock_ai({**EXTRACTION, "importance": None, "importance_rationale": None})
    post_inbound()
    intake = Intake.objects.get()
    assert intake.importance == 4
    assert intake.assessment == ""
    assert intake.assessed_at is None


def test_normal_importance_gets_no_assessment(user, mock_ai):
    mock_ai({**EXTRACTION, "importance": 4, "importance_rationale": "Routine."})
    post_inbound()
    intake = Intake.objects.get()
    assert intake.importance == 4
    assert intake.assessment == ""


def test_invalid_importance_ignored(user, mock_ai):
    mock_ai({**EXTRACTION, "importance": "very high", "importance_rationale": "x"})
    post_inbound()
    intake = Intake.objects.get()
    assert intake.importance == 4
    assert intake.assessment == ""


def test_out_of_range_importance_clamped(user, mock_ai):
    mock_ai({**EXTRACTION, "importance": 11, "importance_rationale": "Big case."})
    post_inbound()
    assert Intake.objects.get().importance == 7


def test_followup_by_email_logs_note_on_existing_intake(user, intake, mock_ai):
    # intake fixture: email contact@example.com, phone 123.456.7890
    mock_ai({**EXTRACTION, "email": "Contact@Example.com"})
    post_inbound()
    assert Intake.objects.count() == 1  # no duplicate
    note = Note.objects.get()
    assert note.intake_id == intake.id
    assert note.type == "Email In"
    assert note.user.username == "kosmos"
    assert InboundEmail.objects.get().intake_id == intake.id


def test_followup_by_phone_matches_despite_formatting(user, intake, mock_ai):
    # Stored as 123.456.7890; extracted with different punctuation
    mock_ai({**EXTRACTION, "email": None, "phone": "(123) 456-7890"})
    post_inbound()
    assert Intake.objects.count() == 1
    assert Note.objects.get().intake_id == intake.id


def test_followup_reopens_unresponsive_intake(user, intake, mock_ai):
    Intake.objects.filter(id=intake.id).update(status="Unresponsive")
    mock_ai({**EXTRACTION, "email": "contact@example.com"})
    post_inbound()
    intake.refresh_from_db()
    assert intake.status == "Open"


def test_followup_leaves_pending_intake_alone(user, intake, mock_ai):
    # Pending means the intake is being migrated to a client
    Intake.objects.filter(id=intake.id).update(status="Pending")
    mock_ai({**EXTRACTION, "email": "contact@example.com"})
    post_inbound()
    intake.refresh_from_db()
    assert intake.status == "Pending"


def test_followup_matches_most_recent_intake(user, intake, mock_ai):
    newer = Intake.objects.create(
        name="Second Matter", email="contact@example.com", date="2025-01-01"
    )
    mock_ai({**EXTRACTION, "email": "contact@example.com"})
    post_inbound()
    assert Note.objects.get().intake_id == newer.id


def test_followup_does_not_touch_fields_or_assessment(user, intake, mock_ai):
    mock_ai(
        {
            **EXTRACTION,
            "email": "contact@example.com",
            "importance": 7,
            "importance_rationale": "Huge case.",
        }
    )
    post_inbound()
    intake.refresh_from_db()
    assert intake.importance == 4
    assert intake.assessment == ""
    assert intake.name == "Mohandas Gandhi"


def test_name_is_title_cased(user, mock_ai):
    mock_ai({**EXTRACTION, "name": "jane q. roe"})
    post_inbound()
    assert Intake.objects.get().name == "Jane Q. Roe"


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
