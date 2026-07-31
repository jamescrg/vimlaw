"""Background extraction of email-attachment text.

Fetches supported attachments' bytes transiently from Gmail, extracts text,
stores it on the EmailAttachment row, and discards the bytes — the binary
stays in Gmail (same text-only philosophy as the email bodies). Reuses the
OCR pipeline's pypdf extraction for PDFs and the Drive converter for office
formats. Scanned PDFs with no text layer are marked, not OCR'd.
"""

import base64
import logging
import os

from apps.case.documents.tasks import extract_existing_text, sanitize_text
from apps.drive.convert import to_markdown

from .models import Email, GmailAccount

logger = logging.getLogger(__name__)

# Extensions we can turn into text without OCR. Images are deliberately
# excluded — signature logos would otherwise pollute every thread.
CONVERT_EXTENSIONS = {".docx", ".odt", ".md", ".xlsx", ".ods", ".csv"}
TEXT_EXTENSIONS = {".txt"}
# A PDF whose text layer yields fewer content chars than this is treated as
# scanned (mirrors the OCR pipeline's TEXT_THRESHOLD idea, scaled down for
# short attachments).
PDF_TEXT_THRESHOLD = 200
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


def _fetch_attachment_bytes(service, message_id, attachment_id):
    resp = (
        service.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=message_id, id=attachment_id)
        .execute()
    )
    return base64.urlsafe_b64decode(resp["data"])


def process_email_attachments(email_id):
    """Extract text for an email's pending attachments (django-q task)."""
    from . import google

    email = Email.objects.filter(pk=email_id).first()
    if email is None:
        return None
    pending = list(email.attachment_files.filter(extract_status="pending"))
    if not pending:
        return None
    # The attachment bytes live in the mailbox this row was synced from;
    # legacy NULL-account rows predate multi-account and belong to the
    # first (original) mailbox.
    account = email.account or GmailAccount.objects.order_by("id").first()
    service = google.build_service(account)
    if not service:
        return None  # stays pending; a later run can pick it up
    stats = {"extracted": 0, "skipped": 0, "failed": 0}

    for att in pending:
        ext = os.path.splitext(att.filename)[1].lower()
        supported = ext == ".pdf" or ext in CONVERT_EXTENSIONS or ext in TEXT_EXTENSIONS
        if (
            not supported
            or not att.gmail_attachment_id
            or att.size > MAX_ATTACHMENT_BYTES
        ):
            att.extract_status = "unsupported"
            att.save(update_fields=["extract_status"])
            stats["skipped"] += 1
            continue

        try:
            content = _fetch_attachment_bytes(
                service, email.gmail_id, att.gmail_attachment_id
            )
            if ext == ".pdf":
                text, _pages, content_chars = extract_existing_text(content)
                if content_chars < PDF_TEXT_THRESHOLD:
                    att.extract_status = "no_text_layer"
                    att.save(update_fields=["extract_status"])
                    stats["skipped"] += 1
                    continue
            elif ext in TEXT_EXTENSIONS:
                text = content.decode("utf-8", errors="replace")
            else:
                text = to_markdown(content, ext)

            att.text = sanitize_text(text)
            att.extract_status = "extracted"
            att.save(update_fields=["text", "extract_status"])
            stats["extracted"] += 1
        except Exception:
            att.extract_status = "failed"
            att.save(update_fields=["extract_status"])
            stats["failed"] += 1
            logger.exception(
                "Attachment extraction failed: %s (email %s)", att.filename, email_id
            )

    return stats
