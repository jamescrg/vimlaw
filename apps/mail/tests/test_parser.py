from datetime import timezone as dt_timezone

from apps.mail.parser import html_to_text, parse_payload

from .conftest import b64, gmail_message


def test_plain_single_part():
    parsed = parse_payload(gmail_message("m1", body="Hello there"))
    assert parsed.body_text == "Hello there"
    assert parsed.body_source == "plain"
    assert parsed.sender == "Alice <alice@example.com>"
    assert parsed.recipients == "Bob <bob@example.com>"
    assert parsed.subject == "Test subject"


def test_internal_date_parsed_as_utc():
    parsed = parse_payload(gmail_message("m1", internal_ms=1753800000000))
    assert parsed.date is not None
    assert parsed.date.tzinfo == dt_timezone.utc
    assert parsed.date.year == 2025


def test_multipart_prefers_plain_over_html():
    msg = gmail_message("m1")
    msg["payload"] = {
        "mimeType": "multipart/alternative",
        "headers": msg["payload"]["headers"],
        "parts": [
            {
                "mimeType": "text/html",
                "filename": "",
                "body": {"data": b64("<p>HTML version</p>")},
            },
            {
                "mimeType": "text/plain",
                "filename": "",
                "body": {"data": b64("Plain version")},
            },
        ],
    }
    parsed = parse_payload(msg)
    assert parsed.body_text == "Plain version"
    assert parsed.body_source == "plain"


def test_html_only_falls_back_to_text():
    msg = gmail_message("m1")
    msg["payload"] = {
        "mimeType": "text/html",
        "headers": msg["payload"]["headers"],
        "body": {
            "data": b64(
                "<html><head><style>p{color:red}</style></head>"
                "<body><p>First &amp; second</p><p>Third</p></body></html>"
            )
        },
    }
    parsed = parse_payload(msg)
    assert parsed.body_source == "html"
    # Raw HTML retained for the preview pane / promoted PDFs.
    assert "<p>" in parsed.body_html
    assert "First & second" in parsed.body_text
    assert "Third" in parsed.body_text
    assert "color:red" not in parsed.body_text
    # Block elements become line breaks.
    assert parsed.body_text.index("second") < parsed.body_text.index("Third")


def test_nested_multipart_with_attachment():
    msg = gmail_message("m1")
    msg["payload"] = {
        "mimeType": "multipart/mixed",
        "headers": msg["payload"]["headers"] + [{"name": "Cc", "value": "c@x.com"}],
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "filename": "",
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "filename": "",
                        "body": {"data": b64("Body text")},
                    },
                    {
                        "mimeType": "text/html",
                        "filename": "",
                        "body": {"data": b64("<p>Body text</p>")},
                    },
                ],
            },
            {
                "mimeType": "application/pdf",
                "filename": "contract.pdf",
                "body": {"attachmentId": "att1", "size": 12345},
            },
        ],
    }
    parsed = parse_payload(msg)
    assert parsed.body_text == "Body text"
    assert parsed.attachments == [
        {"filename": "contract.pdf", "mime_type": "application/pdf", "size": 12345}
    ]
    assert parsed.recipients == "Bob <bob@example.com>, c@x.com"


def test_inline_image_with_filename_recorded_not_fetched():
    msg = gmail_message("m1")
    msg["payload"]["parts"] = [
        {
            "mimeType": "image/png",
            "filename": "logo.png",
            "body": {"attachmentId": "att2", "size": 999},
        }
    ]
    parsed = parse_payload(msg)
    assert parsed.attachments[0]["filename"] == "logo.png"


def test_missing_headers_and_date():
    msg = {"id": "m1", "payload": {"mimeType": "text/plain", "headers": []}}
    parsed = parse_payload(msg)
    assert parsed.sender == ""
    assert parsed.subject == ""
    assert parsed.date is None
    assert parsed.body_text == ""


def test_html_to_text_strips_script_and_entities():
    text = html_to_text("<script>alert(1)</script><div>A &lt; B</div>")
    assert "alert" not in text
    assert "A < B" in text


def test_nul_bytes_stripped():
    parsed = parse_payload(gmail_message("m1", body="bad\x00byte"))
    assert "\x00" not in parsed.body_text
