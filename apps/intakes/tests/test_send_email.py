import pytest
from django.core import mail

from apps.intakes.models import IntakeEmailTemplate, Note
from apps.settings.models import Firm

pytestmark = pytest.mark.django_db


@pytest.fixture
def firm():
    return Firm.objects.create(
        name="Craig Legal, LLC",
        email="james@example.com",
        intake_email="intakes@example.com",
    )


@pytest.fixture
def template():
    return IntakeEmailTemplate.objects.create(
        name="Rejection",
        subject="Regarding your inquiry",
        body="Dear prospective client,\n\nWe are unable to take your matter.",
    )


def test_modal_lists_templates(client, intake, template):
    response = client.get(f"/intakes/{intake.id}/send-email")
    assert response.status_code == 200
    assert b"Rejection" in response.content
    assert intake.email.encode() in response.content


def test_send_happy_path(client, user, intake, firm, template):
    response = client.post(
        f"/intakes/{intake.id}/send-email/send",
        {"subject": "Regarding your inquiry", "body": "Dear Mr. Gandhi,\n\nNo."},
    )
    assert response.status_code == 204
    assert response.headers["HX-Trigger"] == "intakeDetailChanged"

    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.to == [intake.email]
    assert sent.cc == ["intakes@example.com"]
    assert "intakes@example.com" in sent.reply_to[0]
    assert "Craig Legal" in sent.from_email
    assert sent.subject == "Regarding your inquiry"
    assert sent.body.startswith("Dear Mr. Gandhi,")
    # Multipart: HTML alternative carries the same text with line breaks
    html, mimetype = sent.alternatives[0]
    assert mimetype == "text/html"
    assert "Dear Mr. Gandhi," in html
    assert "<br" in html

    note = Note.objects.get()
    assert note.intake_id == intake.id
    assert note.user_id == user.id  # tagged to the sender
    assert note.type == "Email Out"
    assert "Regarding your inquiry" in note.details
    assert "Dear Mr. Gandhi," in note.details


def test_no_cc_when_intake_email_unset(client, intake, template):
    Firm.objects.create(name="Craig Legal", email="james@example.com")
    client.post(
        f"/intakes/{intake.id}/send-email/send",
        {"subject": "S", "body": "B"},
    )
    assert mail.outbox[0].cc == []


def test_intake_without_email_blocked(client, firm, practice_area):
    from apps.intakes.models import Intake

    intake = Intake.objects.create(name="No Email", date="2026-01-01")
    response = client.post(
        f"/intakes/{intake.id}/send-email/send",
        {"subject": "S", "body": "B"},
    )
    assert response.status_code == 200
    assert b"no email address" in response.content
    assert len(mail.outbox) == 0
    assert Note.objects.count() == 0


def test_blank_subject_rerenders_with_error(client, intake, firm):
    response = client.post(
        f"/intakes/{intake.id}/send-email/send",
        {"subject": "", "body": "Something"},
    )
    assert response.status_code == 200
    assert b"required" in response.content
    assert len(mail.outbox) == 0


def test_send_failure_logs_nothing(client, intake, firm, monkeypatch):
    def boom(self):
        raise RuntimeError("SMTP down")

    monkeypatch.setattr("django.core.mail.EmailMessage.send", boom)
    response = client.post(
        f"/intakes/{intake.id}/send-email/send",
        {"subject": "S", "body": "Body text"},
    )
    assert response.status_code == 200
    assert b"Send failed" in response.content
    assert Note.objects.count() == 0
