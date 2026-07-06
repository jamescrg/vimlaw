import pytest
from django.core.files.base import ContentFile

from apps.invoicing.invoices.functions.send_invoice import (
    _invalid_addresses,
    _parse_recipients,
    send_invoice,
)
from apps.settings.models import Firm

# Local filesystem storage + in-memory email so the send path can run without
# touching S3 or SMTP.
_LOCAL_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def _offline_send_env(settings, tmp_path):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.STORAGES = _LOCAL_STORAGES
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", []),
        (None, []),
        ("a@x.com", ["a@x.com"]),
        ("a@x.com, b@y.com", ["a@x.com", "b@y.com"]),
        ("a@x.com,b@y.com", ["a@x.com", "b@y.com"]),
        ("  a@x.com ;  b@y.com ", ["a@x.com", "b@y.com"]),  # ; is treated as ,
        ("a@x.com, , b@y.com,", ["a@x.com", "b@y.com"]),  # blanks dropped
    ],
)
def test_parse_recipients(raw, expected):
    assert _parse_recipients(raw) == expected


def test_invalid_addresses_flags_only_bad_ones():
    addrs = ["good@x.com", "not-an-email", "also@good.org", "@nope"]
    assert _invalid_addresses(addrs) == ["not-an-email", "@nope"]


def test_invalid_addresses_empty_when_all_valid():
    assert _invalid_addresses(["a@x.com", "b@y.com"]) == []


@pytest.mark.django_db
def test_send_invoice_uses_billing_email(invoice, mailoutbox, settings, tmp_path):
    """From uses BILLING_FROM_EMAIL; Reply-To and the in-body contact address
    use the firm's billing email."""
    _offline_send_env(settings, tmp_path)
    settings.BILLING_FROM_EMAIL = "billing-sender@example.com"
    invoice.pdf_file.save("inv.pdf", ContentFile(b"%PDF-1.4 test"), save=True)
    Firm.objects.create(
        name="Craig Legal",
        email="firm@example.com",
        billing_email="billing@example.com",
    )

    assert send_invoice(invoice, to="client@example.com") is True
    assert len(mailoutbox) == 1
    msg = mailoutbox[0]
    # Sent from the configured billing sender, with the firm as display name.
    assert "billing-sender@example.com" in msg.from_email
    assert "Craig Legal" in msg.from_email
    assert msg.reply_to == ["billing@example.com"]
    assert "billing@example.com" in msg.body
    assert "firm@example.com" not in msg.body
    html = msg.alternatives[0][0]
    assert "billing@example.com" in html


@pytest.mark.django_db
def test_send_invoice_falls_back_to_firm_email(invoice, mailoutbox, settings, tmp_path):
    """With no billing email configured, correspondence uses the firm email."""
    _offline_send_env(settings, tmp_path)
    invoice.pdf_file.save("inv.pdf", ContentFile(b"%PDF-1.4 test"), save=True)
    Firm.objects.create(name="Craig Legal", email="firm@example.com")

    assert send_invoice(invoice, to="client@example.com") is True
    msg = mailoutbox[0]
    assert msg.reply_to == ["firm@example.com"]
    assert "firm@example.com" in msg.body
