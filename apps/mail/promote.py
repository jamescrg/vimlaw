"""Promote a synced email to a matter Document.

Renders the email through the existing mbox email-PDF pipeline (WeasyPrint +
templates/case/documents/email_pdf.html) and files it as a real Document —
category Correspondence, date and description from the email. The Document is
a copy across the sync boundary: nothing Gmail-side (unlabel, trash, sync
error) can touch it, which is what makes it safe to carry highlights.
"""

import os

from django.core.files.base import ContentFile
from django_q.tasks import async_task

from apps.case.documents.mbox import (
    EmailMetadata,
    extract_last_name,
    generate_email_description,
    generate_email_pdf,
    parse_email_address,
)
from apps.case.models import Document


def _email_metadata(email):
    """Bridge an Email row into the mbox pipeline's EmailMetadata."""
    sender_name, sender_email = parse_email_address(email.sender or "")
    first_recipient = (email.recipients or "").split(",")[0].strip()
    recipient_name, recipient_email = parse_email_address(first_recipient)

    return EmailMetadata(
        sender_full=sender_name or sender_email,
        sender_last=extract_last_name(sender_name, sender_email),
        sender_email=sender_email,
        recipient_full=recipient_name or recipient_email,
        recipient_last=extract_last_name(recipient_name, recipient_email),
        recipient_email=recipient_email,
        subject=email.subject or "(no subject)",
        date=email.date,
        body_html=email.body_html,
        body_text=email.body_text,
    )


def promote_email(email, user, base_url):
    """Create a Correspondence Document from the email. Returns the Document.

    Idempotent: returns the existing Document if the email is already
    promoted. On success the email's ai_context flips to "never" so the AI
    reads the Document instead of the raw email row.
    """
    if email.document:
        return email.document

    metadata = _email_metadata(email)
    pdf_file = generate_email_pdf(metadata, base_url)

    document = Document(
        matter=email.matter,
        name=(email.subject or "(no subject)")[:100],
        description=generate_email_description(metadata),
        category="Correspondence",
        date=email.date.date() if email.date else None,
        created_by=user,
    )
    document.save()

    with open(pdf_file.name, "rb") as f:
        pdf_content = f.read()
    os.unlink(pdf_file.name)

    document.file.save(f"{document.pk}.pdf", ContentFile(pdf_content), save=True)

    if not document.file.storage.exists(document.file.name):
        document.delete()
        raise RuntimeError("Promoted PDF did not save to storage.")

    try:
        async_task(
            "apps.case.documents.tasks.process_document_ocr",
            document.id,
            task_name=f"OCR-{document.id}",
            group="ocr_processing",
        )
    except Exception:
        from apps.case.documents.tasks import process_document_ocr

        process_document_ocr(document.id)

    email.document = document
    email.ai_context = "never"
    email.save(update_fields=["document", "ai_context"])

    return document
