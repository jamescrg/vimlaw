"""The one-time adopt_gmail_account migration command."""

import pytest
from django.core.management import call_command

from apps.mail.models import Email, GmailSyncState

from .conftest import gmail_message

pytestmark = pytest.mark.django_db


def test_adopt_claims_rows_and_backfills(matter, fake_gmail):
    # Legacy single-mailbox state: account-less rows, blank message_id, and
    # the old singleton cursor.
    fake_gmail.messages = {"m1": gmail_message("m1")}
    Email.objects.create(matter=matter, gmail_id="m1", thread_id="t1")
    GmailSyncState.objects.create(pk=1, history_id="1500")

    call_command("adopt_gmail_account", "testuser")

    email = Email.objects.get()
    assert email.account == fake_gmail.account
    assert email.message_id == "<m1@mail.example.com>"
    fake_gmail.account.refresh_from_db()
    # Address refreshed from the mailbox, cursor carried over.
    assert fake_gmail.account.address == "primary@example.com"
    assert fake_gmail.account.history_id == "1500"


def test_adopt_skip_backfill(matter, fake_gmail):
    Email.objects.create(matter=matter, gmail_id="m1", thread_id="t1")
    call_command("adopt_gmail_account", "testuser", "--skip-backfill")
    email = Email.objects.get()
    assert email.account == fake_gmail.account
    assert email.message_id == ""
