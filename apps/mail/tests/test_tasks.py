import pytest
from django.utils import timezone
from weasyprint import HTML

from apps.mail.models import Email, EmailAttachment
from apps.mail.tasks import process_email_attachments

pytestmark = pytest.mark.django_db


def make_email_with_attachment(matter, filename, attachment_id="att-1", size=1000):
    email = Email.objects.create(
        matter=matter,
        gmail_id="m1",
        thread_id="thread-1",
        sender="alice@example.com",
        subject="With attachment",
        date=timezone.now(),
        body_text="See attached.",
    )
    att = EmailAttachment.objects.create(
        email=email,
        gmail_attachment_id=attachment_id,
        filename=filename,
        size=size,
    )
    return email, att


def test_pdf_attachment_text_extracted(matter, fake_gmail):
    pdf_bytes = HTML(
        string="<p>" + "Settlement agreement terms and conditions. " * 20 + "</p>"
    ).write_pdf()
    fake_gmail.attachment_data["att-1"] = pdf_bytes

    email, att = make_email_with_attachment(matter, "agreement.pdf")
    stats = process_email_attachments(email.id)

    att.refresh_from_db()
    assert stats["extracted"] == 1
    assert att.extract_status == "extracted"
    assert "Settlement agreement terms" in att.text


def test_pdf_without_text_layer_marked(matter, fake_gmail):
    # A blank-page PDF has a valid structure but no meaningful text content.
    fake_gmail.attachment_data["att-1"] = HTML(string="<p></p>").write_pdf()
    email, att = make_email_with_attachment(matter, "scan.pdf")
    process_email_attachments(email.id)
    att.refresh_from_db()
    assert att.extract_status == "no_text_layer"
    assert att.text == ""


def test_csv_attachment_converted(matter, fake_gmail):
    fake_gmail.attachment_data["att-1"] = b"name,amount\nfiling fee,402\n"
    email, att = make_email_with_attachment(matter, "costs.csv")
    process_email_attachments(email.id)
    att.refresh_from_db()
    assert att.extract_status == "extracted"
    assert "filing fee" in att.text


def test_image_attachment_unsupported(matter, fake_gmail):
    email, att = make_email_with_attachment(matter, "image001.png")
    stats = process_email_attachments(email.id)
    att.refresh_from_db()
    assert att.extract_status == "unsupported"
    assert stats["skipped"] == 1


def test_fetch_failure_marked_failed(matter, fake_gmail):
    # No attachment_data registered -> fake service 404s the fetch.
    email, att = make_email_with_attachment(matter, "missing.pdf")
    process_email_attachments(email.id)
    att.refresh_from_db()
    assert att.extract_status == "failed"


def test_oversized_attachment_skipped(matter, fake_gmail):
    email, att = make_email_with_attachment(matter, "huge.pdf", size=25 * 1024 * 1024)
    process_email_attachments(email.id)
    att.refresh_from_db()
    assert att.extract_status == "unsupported"


def test_sync_creates_attachment_rows_and_queues(matter, fake_gmail, monkeypatch):
    import apps.mail.google as google

    from .conftest import b64, gmail_message

    queued = []
    monkeypatch.setattr(
        "django_q.tasks.async_task", lambda func, *args, **kwargs: queued.append(args)
    )

    msg = gmail_message("m9", label_ids=("Label_1",))
    msg["payload"] = {
        "mimeType": "multipart/mixed",
        "headers": msg["payload"]["headers"],
        "parts": [
            {
                "mimeType": "text/plain",
                "filename": "",
                "body": {"data": b64("Body")},
            },
            {
                "mimeType": "application/pdf",
                "filename": "exhibit.pdf",
                "body": {"attachmentId": "gmail-att-id-long", "size": 5000},
            },
        ],
    }
    fake_gmail.messages = {"m9": msg}
    google.sync(full=True)

    email = Email.objects.get(gmail_id="m9")
    att = email.attachment_files.get()
    assert att.filename == "exhibit.pdf"
    assert att.gmail_attachment_id == "gmail-att-id-long"
    assert att.extract_status == "pending"
    assert queued == [(email.id,)]
