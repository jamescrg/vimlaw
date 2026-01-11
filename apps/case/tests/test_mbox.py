"""Tests for mbox email processing."""

import pytest

from apps.case.documents.mbox import (
    extract_last_name,
    generate_email_description,
    parse_email_address,
    parse_mbox_file,
    sanitize_html_for_pdf,
    text_to_html,
)


class TestExtractLastName:
    def test_first_last_format(self):
        assert extract_last_name("John Smith", "") == "Smith"

    def test_last_first_format(self):
        assert extract_last_name("Smith, John", "") == "Smith"

    def test_single_name(self):
        assert extract_last_name("Smith", "") == "Smith"

    def test_multiple_names(self):
        assert extract_last_name("John Paul Smith", "") == "Smith"

    def test_empty_name_with_email(self):
        assert extract_last_name("", "jsmith@example.com") == "Jsmith"

    def test_whitespace_only_name_with_email(self):
        assert extract_last_name("   ", "jsmith@example.com") == "Jsmith"

    def test_empty_both(self):
        assert extract_last_name("", "") == "Unknown"


class TestParseEmailAddress:
    def test_name_and_email(self):
        name, email = parse_email_address("John Smith <john@example.com>")
        assert name == "John Smith"
        assert email == "john@example.com"

    def test_email_only(self):
        name, email = parse_email_address("john@example.com")
        assert name == ""
        assert email == "john@example.com"

    def test_quoted_name(self):
        name, email = parse_email_address('"Smith, John" <john@example.com>')
        assert name == "Smith, John"
        assert email == "john@example.com"

    def test_empty(self):
        name, email = parse_email_address("")
        assert name == ""
        assert email == ""


class TestSanitizeHtml:
    def test_removes_script_tags(self):
        html = '<p>Hello</p><script>alert("xss")</script>'
        result = sanitize_html_for_pdf(html)
        assert "<script>" not in result
        assert "<p>Hello</p>" in result

    def test_removes_style_tags(self):
        html = "<style>body{color:red}</style><p>Hello</p>"
        result = sanitize_html_for_pdf(html)
        assert "<style>" not in result
        assert "<p>Hello</p>" in result

    def test_removes_onclick(self):
        html = '<a href="#" onclick="evil()">Link</a>'
        result = sanitize_html_for_pdf(html)
        assert "onclick" not in result
        assert "<a href=" in result

    def test_removes_onload(self):
        html = '<img src="x" onload="evil()">'
        result = sanitize_html_for_pdf(html)
        assert "onload" not in result

    def test_empty_string(self):
        assert sanitize_html_for_pdf("") == ""


class TestTextToHtml:
    def test_escapes_html(self):
        text = "Hello <world> & friends"
        result = text_to_html(text)
        assert "&lt;world&gt;" in result
        assert "&amp;" in result

    def test_converts_newlines(self):
        text = "Line 1\nLine 2"
        result = text_to_html(text)
        assert "<br>" in result

    def test_empty_string(self):
        assert text_to_html("") == ""


class TestParseMboxFile:
    @pytest.fixture
    def simple_mbox(self):
        """A simple mbox file with one email."""
        return b"""From sender@example.com Mon Jan 01 12:00:00 2024
From: John Smith <john@example.com>
To: Jane Doe <jane@example.com>
Subject: Test Email
Date: Mon, 01 Jan 2024 12:00:00 +0000
Content-Type: text/plain

This is the email body.
"""

    @pytest.fixture
    def multi_email_mbox(self):
        """An mbox file with multiple emails."""
        return b"""From sender@example.com Mon Jan 01 12:00:00 2024
From: John Smith <john@example.com>
To: Jane Doe <jane@example.com>
Subject: First Email
Date: Mon, 01 Jan 2024 12:00:00 +0000
Content-Type: text/plain

First email body.

From sender2@example.com Mon Jan 02 12:00:00 2024
From: Bob Jones <bob@example.com>
To: Alice Smith <alice@example.com>
Subject: Second Email
Date: Tue, 02 Jan 2024 12:00:00 +0000
Content-Type: text/plain

Second email body.
"""

    def test_parses_single_email(self, simple_mbox):
        metadata = parse_mbox_file(simple_mbox)
        assert metadata.sender_full == "John Smith"
        assert metadata.sender_last == "Smith"
        assert metadata.sender_email == "john@example.com"
        assert metadata.recipient_full == "Jane Doe"
        assert metadata.recipient_last == "Doe"
        assert metadata.recipient_email == "jane@example.com"
        assert metadata.subject == "Test Email"
        assert "email body" in metadata.body_text

    def test_parses_date(self, simple_mbox):
        metadata = parse_mbox_file(simple_mbox)
        assert metadata.date is not None
        assert metadata.date.year == 2024
        assert metadata.date.month == 1
        assert metadata.date.day == 1

    def test_rejects_multi_email_mbox(self, multi_email_mbox):
        with pytest.raises(ValueError) as exc_info:
            parse_mbox_file(multi_email_mbox)
        assert "multiple emails" in str(exc_info.value).lower()

    def test_rejects_empty_mbox(self):
        with pytest.raises(ValueError) as exc_info:
            parse_mbox_file(b"")
        assert "no valid emails" in str(exc_info.value).lower()

    def test_handles_missing_name(self):
        mbox = b"""From sender@example.com Mon Jan 01 12:00:00 2024
From: john@example.com
To: jane@example.com
Subject: Test
Date: Mon, 01 Jan 2024 12:00:00 +0000
Content-Type: text/plain

Body
"""
        metadata = parse_mbox_file(mbox)
        # Should fall back to email local part
        assert metadata.sender_last == "John"
        assert metadata.recipient_last == "Jane"

    def test_handles_no_subject(self):
        mbox = b"""From sender@example.com Mon Jan 01 12:00:00 2024
From: John Smith <john@example.com>
To: Jane Doe <jane@example.com>
Date: Mon, 01 Jan 2024 12:00:00 +0000
Content-Type: text/plain

Body
"""
        metadata = parse_mbox_file(mbox)
        assert metadata.subject == "(No Subject)"


class TestGenerateEmailDescription:
    def test_basic_description(self):
        from apps.case.documents.mbox import EmailMetadata

        metadata = EmailMetadata(
            sender_full="John Smith",
            sender_last="Smith",
            sender_email="john@example.com",
            recipient_full="Jane Doe",
            recipient_last="Doe",
            recipient_email="jane@example.com",
            subject="Meeting Notes",
            date=None,
            body_html="",
            body_text="Body",
        )
        desc = generate_email_description(metadata)
        assert desc == "Email from Smith to Doe RE Meeting Notes"

    def test_long_subject_truncated(self):
        from apps.case.documents.mbox import EmailMetadata

        long_subject = "A" * 150
        metadata = EmailMetadata(
            sender_full="John",
            sender_last="Smith",
            sender_email="",
            recipient_full="Jane",
            recipient_last="Doe",
            recipient_email="",
            subject=long_subject,
            date=None,
            body_html="",
            body_text="",
        )
        desc = generate_email_description(metadata)
        assert len(desc) < 150
        assert desc.endswith("...")
