"""Mbox email file processing for document conversion to PDF."""

import email
import html
import mailbox
import os
import re
from datetime import datetime
from email.utils import parseaddr, parsedate_to_datetime
from tempfile import NamedTemporaryFile
from typing import NamedTuple

from django.template.loader import render_to_string
from weasyprint import HTML


class EmailMetadata(NamedTuple):
    """Parsed email metadata for document creation."""

    sender_full: str
    sender_last: str
    sender_email: str
    recipient_full: str
    recipient_last: str
    recipient_email: str
    subject: str
    date: datetime | None
    body_html: str
    body_text: str


def extract_last_name(full_name: str, email_addr: str) -> str:
    """
    Extract last name from full name or email address.

    Examples:
        "John Smith" -> "Smith"
        "Smith, John" -> "Smith"
        "" with email "jsmith@example.com" -> "Jsmith"
    """
    if not full_name or not full_name.strip():
        # Fall back to email local part
        local_part = email_addr.split("@")[0] if email_addr else "Unknown"
        return local_part.title()

    full_name = full_name.strip()

    # Handle "Last, First" format
    if "," in full_name:
        return full_name.split(",")[0].strip()

    # Handle "First Last" format - take the last word
    parts = full_name.split()
    return parts[-1] if parts else "Unknown"


def parse_email_address(header_value: str) -> tuple[str, str]:
    """
    Parse email header to extract name and email address.

    Returns:
        tuple of (display_name, email_address)
    """
    if not header_value:
        return ("", "")

    name, email_addr = parseaddr(header_value)
    return (name, email_addr)


def get_email_body(message: email.message.Message) -> tuple[str, str]:
    """
    Extract email body, preferring HTML but falling back to plain text.

    Returns:
        tuple of (html_body, text_body)
    """
    html_body = ""
    text_body = ""

    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            # Skip attachments
            if "attachment" in content_disposition:
                continue

            try:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        decoded = payload.decode(charset, errors="replace")
                    except (LookupError, UnicodeDecodeError):
                        decoded = payload.decode("utf-8", errors="replace")

                    if content_type == "text/html":
                        html_body = decoded
                    elif content_type == "text/plain" and not text_body:
                        text_body = decoded
            except Exception:
                continue
    else:
        content_type = message.get_content_type()
        try:
            payload = message.get_payload(decode=True)
            if payload:
                charset = message.get_content_charset() or "utf-8"
                try:
                    decoded = payload.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    decoded = payload.decode("utf-8", errors="replace")

                if content_type == "text/html":
                    html_body = decoded
                else:
                    text_body = decoded
        except Exception:
            pass

    return (html_body, text_body)


def parse_mbox_file(file_content: bytes) -> EmailMetadata:
    """
    Parse an mbox file and extract the first email's metadata.

    Args:
        file_content: Raw bytes of the mbox file

    Returns:
        EmailMetadata with parsed email information

    Raises:
        ValueError: If mbox contains no valid emails or multiple emails
    """
    # Write to temp file for mailbox module
    with NamedTemporaryFile(suffix=".mbox", delete=False) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    try:
        mbox = mailbox.mbox(tmp_path)
        messages = list(mbox)

        if len(messages) == 0:
            raise ValueError("No valid emails found in mbox file")

        if len(messages) > 1:
            raise ValueError(
                "Mbox file contains multiple emails. Please export a single email."
            )

        message = messages[0]

        # Parse sender
        from_header = message.get("From", "")
        sender_name, sender_email = parse_email_address(from_header)
        sender_last = extract_last_name(sender_name, sender_email)

        # Parse recipient (first To: address)
        to_header = message.get("To", "")
        # Handle multiple recipients - take the first one
        first_recipient = to_header.split(",")[0].strip() if to_header else ""
        recipient_name, recipient_email = parse_email_address(first_recipient)
        recipient_last = extract_last_name(recipient_name, recipient_email)

        # Parse subject
        subject = message.get("Subject", "")
        # Decode if needed
        if subject:
            try:
                decoded_parts = email.header.decode_header(subject)
                subject = "".join(
                    (
                        part.decode(charset or "utf-8", errors="replace")
                        if isinstance(part, bytes)
                        else part
                    )
                    for part, charset in decoded_parts
                )
            except Exception:
                pass

        # Parse date
        date_header = message.get("Date", "")
        email_date = None
        if date_header:
            try:
                email_date = parsedate_to_datetime(date_header)
            except Exception:
                pass

        # Get body content
        html_body, text_body = get_email_body(message)

        return EmailMetadata(
            sender_full=sender_name or sender_email,
            sender_last=sender_last,
            sender_email=sender_email,
            recipient_full=recipient_name or recipient_email,
            recipient_last=recipient_last,
            recipient_email=recipient_email,
            subject=subject or "(No Subject)",
            date=email_date,
            body_html=html_body,
            body_text=text_body,
        )

    finally:
        os.unlink(tmp_path)


def sanitize_html_for_pdf(html_content: str) -> str:
    """
    Clean HTML content for safe PDF rendering.

    Removes scripts, external resources, etc.
    """
    if not html_content:
        return ""

    # Remove script tags
    html_content = re.sub(
        r"<script[^>]*>.*?</script>", "", html_content, flags=re.DOTALL | re.IGNORECASE
    )

    # Remove style tags (we'll use our own styling)
    html_content = re.sub(
        r"<style[^>]*>.*?</style>", "", html_content, flags=re.DOTALL | re.IGNORECASE
    )

    # Remove onclick/onload/etc event handlers
    html_content = re.sub(
        r'\s+on\w+\s*=\s*["\'][^"\']*["\']', "", html_content, flags=re.IGNORECASE
    )

    return html_content


def text_to_html(text_content: str) -> str:
    """Convert plain text to HTML with proper formatting."""
    if not text_content:
        return ""

    escaped = html.escape(text_content)
    # Convert newlines to <br> tags
    return escaped.replace("\n", "<br>\n")


def generate_email_pdf(
    email_metadata: EmailMetadata, base_url: str
) -> NamedTemporaryFile:
    """
    Generate a PDF from email metadata using WeasyPrint.

    Args:
        email_metadata: Parsed email information
        base_url: Base URL for resolving static assets

    Returns:
        NamedTemporaryFile containing the PDF
    """
    # Prepare body content
    if email_metadata.body_html:
        body_content = sanitize_html_for_pdf(email_metadata.body_html)
        is_html = True
    else:
        body_content = text_to_html(email_metadata.body_text)
        is_html = False

    context = {
        "sender_full": email_metadata.sender_full,
        "sender_email": email_metadata.sender_email,
        "recipient_full": email_metadata.recipient_full,
        "recipient_email": email_metadata.recipient_email,
        "subject": email_metadata.subject,
        "date": email_metadata.date,
        "body_content": body_content,
        "is_html_body": is_html,
    }

    html_string = render_to_string("case/documents/email_pdf.html", context)
    html_obj = HTML(string=html_string, base_url=base_url)

    pdf_file = NamedTemporaryFile(suffix=".pdf", delete=False)
    html_obj.write_pdf(target=pdf_file.name)
    pdf_file.seek(0)

    return pdf_file


def generate_email_description(email_metadata: EmailMetadata) -> str:
    """
    Generate document description from email metadata.

    Format: "Email from {sender last} to {recipient last} RE {subject}"
    """
    subject = email_metadata.subject
    # Truncate very long subjects
    if len(subject) > 100:
        subject = subject[:97] + "..."

    return f"Email from {email_metadata.sender_last} to {email_metadata.recipient_last} RE {subject}"
