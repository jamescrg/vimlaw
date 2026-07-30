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


def test_emails_tab_renders_list(client, matter, fake_gmail):
    make_email(matter, "m1", sender="Alice Smith <alice@example.com>")
    response = client.get(reverse("case:emails-index", args=[matter.id]))
    assert response.status_code == 200
    content = response.content.decode()
    assert "Discovery schedule" in content
    # List rows show the parsed display name, not the raw header.
    assert "Alice Smith" in content
    assert "Select an email to read" in content


def test_email_preview_pane(client, matter, fake_gmail):
    email = make_email(matter, "m1")
    response = client.get(reverse("case:email-preview", args=[email.id]))
    content = response.content.decode()
    assert "Proposed dates attached." in content
    assert "schedule.pdf" in content
    assert "https://mail.google.com/mail/u/0/#all/m1" in content
    assert "Promote to Document" in content


def test_email_preview_prefers_html(client, matter, fake_gmail):
    email = make_email(matter, "m1", body_html="<p>Rich <b>body</b></p>")
    content = client.get(
        reverse("case:email-preview", args=[email.id])
    ).content.decode()
    assert "srcdoc" in content
    assert "Rich" in content


def test_email_promote_creates_document(
    client, matter, fake_gmail, settings, tmp_path, monkeypatch
):
    from apps.case.models import Document

    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
    settings.MEDIA_ROOT = str(tmp_path)
    ocr_queued = []
    monkeypatch.setattr(
        "django_q.tasks.async_task",
        lambda func, *args, **kwargs: ocr_queued.append(args[0]),
    )

    email = make_email(matter, "m1", body_html="<p>Promote me</p>")
    response = client.post(reverse("case:email-promote", args=[email.id]))
    assert response.status_code == 200

    email.refresh_from_db()
    assert email.document is not None
    assert email.ai_context == "never"
    doc = email.document
    assert doc.matter == matter
    assert doc.category == "Correspondence"
    assert doc.file.storage.exists(doc.file.name)
    assert ocr_queued == [doc.id]
    # Idempotent: a second promote reuses the same Document.
    client.post(reverse("case:email-promote", args=[email.id]))
    email.refresh_from_db()
    assert email.document == doc
    assert Document.objects.count() == 1
    # The pane now offers the Document instead of promotion.
    content = client.get(
        reverse("case:email-preview", args=[email.id])
    ).content.decode()
    assert "View Document" in content


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


def test_filter_modal_renders(client, matter, fake_gmail):
    response = client.get(reverse("case:emails-filter", args=[matter.id]))
    assert response.status_code == 200
    content = response.content.decode()
    assert "Filter Emails" in content
    assert "Subject Keyword" in content


def test_filter_persists_and_narrows(client, matter, fake_gmail):
    make_email(matter, "m1", subject="Discovery schedule")
    make_email(
        matter,
        "m2",
        thread_id="thread-2",
        subject="Settlement offer",
        sender="Carol <carol@example.com>",
    )

    response = client.post(
        reverse("case:emails-filter", args=[matter.id]), {"sender": "carol"}
    )
    assert response.status_code == 204
    assert response.headers["HX-Trigger"] == "emailsChanged"

    content = client.get(
        reverse("case:emails-index", args=[matter.id])
    ).content.decode()
    assert "Settlement offer" in content
    assert "Discovery schedule" not in content

    # Clear Filters restores the full list.
    client.post(reverse("case:emails-filter", args=[matter.id]), {"reset": "true"})
    content = client.get(
        reverse("case:emails-index", args=[matter.id])
    ).content.decode()
    assert "Discovery schedule" in content


def test_keyword_search_narrows_table(client, matter, fake_gmail):
    make_email(matter, "m1", subject="Discovery schedule")
    make_email(matter, "m2", thread_id="thread-2", subject="Settlement offer")

    response = client.get(
        reverse("case:emails-filter-keyword", args=[matter.id]),
        {"keyword": "settlement"},
    )
    content = response.content.decode()
    assert "Settlement offer" in content
    assert "Discovery schedule" not in content


def test_date_range_filter(client, matter, fake_gmail):
    from datetime import timedelta

    old = make_email(matter, "m1", subject="Old mail")
    Email.objects.filter(pk=old.pk).update(date=timezone.now() - timedelta(days=30))
    make_email(matter, "m2", thread_id="thread-2", subject="Recent mail")

    cutoff = (timezone.now() - timedelta(days=7)).date().isoformat()
    client.post(reverse("case:emails-filter", args=[matter.id]), {"date_after": cutoff})
    content = client.get(
        reverse("case:emails-index", args=[matter.id])
    ).content.decode()
    assert "Recent mail" in content
    assert "Old mail" not in content


def test_sort_toggles_direction(client, matter, fake_gmail):
    make_email(matter, "m1", sender="Alice <a@x.com>")
    make_email(matter, "m2", thread_id="thread-2", sender="Zed <z@x.com>")

    response = client.get(
        reverse("case:emails-sort", args=[matter.id, "sender"]), follow=True
    )
    content = response.content.decode()
    assert content.index("Alice") < content.index("Zed")

    response = client.get(
        reverse("case:emails-sort", args=[matter.id, "sender"]), follow=True
    )
    content = response.content.decode()
    assert content.index("Zed") < content.index("Alice")


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
