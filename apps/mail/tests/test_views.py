import pytest
from django.urls import reverse
from django.utils import timezone

from apps.mail.models import Email

pytestmark = pytest.mark.django_db


def make_email(matter, gmail_id, **kwargs):
    defaults = {
        "thread_id": "thread-1",
        "sender": "alice@example.com",
        "recipients": "bob@example.com",
        "subject": "Discovery schedule",
        "date": timezone.now(),
        "body_text": "Proposed dates attached.",
        "attachments": [
            {"filename": "schedule.pdf", "mime_type": "application/pdf", "size": 100}
        ],
    }
    defaults.update(kwargs)
    return Email.objects.create(matter=matter, gmail_id=gmail_id, **defaults)


@pytest.fixture(autouse=True)
def _inline_resync(monkeypatch):
    """Record queued resyncs instead of hitting django-q / Gmail."""
    calls = []
    monkeypatch.setattr(
        "apps.mail.views._queue_resync", lambda matter: calls.append(matter.id)
    )
    return calls


def test_emails_tab_renders(client, matter, fake_gmail):
    make_email(matter, "m1", sender="Alice Smith <alice@example.com>")
    response = client.get(reverse("case:emails-index", args=[matter.id]))
    assert response.status_code == 200
    content = response.content.decode()
    assert "Discovery schedule" in content
    assert "schedule.pdf" in content
    assert "https://mail.google.com/mail/u/0/#all/m1" in content
    # Table shows the parsed display name, not the raw header.
    assert "Alice Smith" in content


def test_email_importance_update(client, matter, fake_gmail):
    email = make_email(matter, "m1")
    response = client.post(reverse("case:email-importance", args=[email.id, 6]))
    assert response.status_code == 200
    email.refresh_from_db()
    assert email.importance == 6

    # Out-of-range values are ignored (URL only admits ints).
    client.post(reverse("case:email-importance", args=[email.id, 9]))
    email.refresh_from_db()
    assert email.importance == 6


def test_emails_tab_prompts_when_unlinked(client, matter, fake_gmail):
    matter.gmail_label_id = None
    matter.save(update_fields=["gmail_label_id"])
    response = client.get(reverse("case:emails-index", args=[matter.id]))
    assert "Link Gmail Label" in response.content.decode()


def test_label_link_modal_marks_taken_labels(client, matter, matter2, fake_gmail):
    response = client.get(reverse("case:emails-label-link-modal", args=[matter.id]))
    content = response.content.decode()
    assert "Smith" in content
    # matter2 already owns Label_2, so it shows as taken.
    assert "linked to Doe v Roe" in content
    # Labels outside GMAIL_LABEL_ROOT are not offered.
    assert "Admin/Billing" not in content


def test_label_link_clash_returns_inline_error(client, matter, matter2, _inline_resync):
    response = client.post(
        reverse("case:emails-label-link", args=[matter.id]),
        {"label": "Label_2", "label_name": "Doe"},
    )
    assert response.status_code == 200
    assert "already" in response.content.decode()
    matter.refresh_from_db()
    assert matter.gmail_label_id == "Label_1"  # unchanged
    assert _inline_resync == []


def test_label_link_sets_fields_and_queues_resync(client, matter, _inline_resync):
    response = client.post(
        reverse("case:emails-label-link", args=[matter.id]),
        {"label": "Label_3", "label_name": "New Label"},
    )
    assert response.status_code == 204
    matter.refresh_from_db()
    assert matter.gmail_label_id == "Label_3"
    assert matter.gmail_label_name == "New Label"
    assert _inline_resync == [matter.id]


def test_label_unlink_clears_fields(client, matter, _inline_resync):
    response = client.post(reverse("case:emails-label-unlink", args=[matter.id]))
    assert response.status_code == 204
    matter.refresh_from_db()
    assert matter.gmail_label_id is None
    assert matter.gmail_label_name is None
    assert _inline_resync == [matter.id]
