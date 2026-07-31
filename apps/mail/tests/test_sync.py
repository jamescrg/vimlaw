import pytest

import apps.mail.google as google
from apps.mail.models import Email

from .conftest import FakeGmailService, gmail_message, http_error

pytestmark = pytest.mark.django_db


def _cursor(fake_gmail):
    fake_gmail.account.refresh_from_db()
    return fake_gmail.account.history_id


def test_bootstrap_creates_rows_per_mapped_label(matter, matter2, fake_gmail):
    fake_gmail.messages = {
        m["id"]: m
        for m in [
            gmail_message("m1", label_ids=("Label_1",)),
            gmail_message("m2", label_ids=("Label_1",), thread_id="thread-2"),
            gmail_message("m3", label_ids=("Label_2",)),
            gmail_message("m4", label_ids=("Label_9",)),  # unmapped label
        ]
    }
    stats = google.sync(full=True)

    assert stats["created"] == 3
    assert Email.objects.filter(matter=matter).count() == 2
    assert Email.objects.filter(matter=matter2).count() == 1
    assert not Email.objects.filter(gmail_id="m4").exists()
    # Every row carries its mailbox.
    assert set(Email.objects.values_list("account", flat=True)) == {
        fake_gmail.account.pk
    }
    # Cursor captured from the profile before listing, onto the account.
    assert _cursor(fake_gmail) == "2000"


def test_bootstrap_idempotent_and_updated_at_stable(matter, fake_gmail):
    fake_gmail.messages = {"m1": gmail_message("m1")}
    google.sync(full=True)
    first = Email.objects.get(gmail_id="m1")

    stats = google.sync(full=True)
    assert stats["created"] == 0
    assert stats["skipped"] == 1
    assert Email.objects.get(gmail_id="m1").updated_at == first.updated_at


def test_bootstrap_reconciles_unlabeled_messages(matter, fake_gmail):
    fake_gmail.messages = {"m1": gmail_message("m1")}
    google.sync(full=True)
    assert Email.objects.count() == 1

    # Label removed in Gmail while sync was down: full pass drops the row.
    fake_gmail.messages = {}
    stats = google.sync(full=True)
    assert stats["removed"] == 1
    assert Email.objects.count() == 0


def test_incremental_labels_added(matter, fake_gmail):
    google.sync(full=True)  # establish cursor
    fake_gmail.messages = {"m1": gmail_message("m1")}
    fake_gmail.history = [
        {"labelsAdded": [{"message": {"id": "m1"}, "labelIds": ["Label_1"]}]}
    ]
    stats = google.sync()
    assert stats["created"] == 1
    assert Email.objects.get(gmail_id="m1").matter == matter


def test_incremental_messages_added(matter, fake_gmail):
    google.sync(full=True)
    fake_gmail.messages = {"m1": gmail_message("m1")}
    fake_gmail.history = [
        {"messagesAdded": [{"message": {"id": "m1", "labelIds": ["Label_1"]}}]}
    ]
    stats = google.sync()
    assert stats["created"] == 1


def test_incremental_label_removed_only_affects_that_matter(
    matter, matter2, fake_gmail
):
    fake_gmail.messages = {"m1": gmail_message("m1", label_ids=("Label_1", "Label_2"))}
    google.sync(full=True)
    assert Email.objects.count() == 2  # one row per matter

    fake_gmail.history = [
        {"labelsRemoved": [{"message": {"id": "m1"}, "labelIds": ["Label_1"]}]}
    ]
    stats = google.sync()
    assert stats["removed"] == 1
    assert not Email.objects.filter(matter=matter).exists()
    assert Email.objects.filter(matter=matter2).exists()


def test_incremental_trash_removes_everywhere(matter, matter2, fake_gmail):
    fake_gmail.messages = {"m1": gmail_message("m1", label_ids=("Label_1", "Label_2"))}
    google.sync(full=True)

    fake_gmail.history = [
        {"labelsAdded": [{"message": {"id": "m1"}, "labelIds": ["TRASH"]}]}
    ]
    stats = google.sync()
    assert stats["removed"] == 2
    assert Email.objects.count() == 0


def test_incremental_messages_deleted(matter, fake_gmail):
    fake_gmail.messages = {"m1": gmail_message("m1")}
    google.sync(full=True)

    fake_gmail.history = [{"messagesDeleted": [{"message": {"id": "m1"}}]}]
    stats = google.sync()
    assert stats["removed"] == 1


def test_expired_history_id_rebootstraps(matter, fake_gmail):
    fake_gmail.messages = {"m1": gmail_message("m1")}
    google.sync(full=True)
    Email.objects.all().delete()

    fake_gmail.history = http_error(404)
    stats = google.sync()
    # Fell back to a full bootstrap and re-ingested the message.
    assert stats["created"] == 1
    assert Email.objects.count() == 1


def test_sync_noops_without_mapping(fake_gmail, db):
    assert google.sync() is None


def test_missing_label_recorded(matter, fake_gmail):
    fake_gmail.labels = [
        {"id": "Label_2", "name": "Matters - Open/Doe", "type": "user"}
    ]
    stats = google.sync(full=True)
    assert stats["missing_labels"] == {"primary@example.com": ["Matters - Open/Smith"]}
    fake_gmail.account.refresh_from_db()
    assert fake_gmail.account.missing_labels == ["Matters - Open/Smith"]


def test_renamed_label_reported_missing_rows_kept(matter, fake_gmail):
    # The NAME is the contract now: a rename in one mailbox orphans the
    # matter there (reported as missing); already-synced rows are kept.
    fake_gmail.messages = {"m1": gmail_message("m1")}
    google.sync(full=True)
    assert Email.objects.count() == 1

    fake_gmail.labels = [
        {"id": "Label_1", "name": "Matters - Open/Smith (new)", "type": "user"}
    ]
    stats = google.sync(full=True)
    assert stats["missing_labels"] == {"primary@example.com": ["Matters - Open/Smith"]}
    assert Email.objects.count() == 1
    matter.refresh_from_db()
    assert matter.gmail_label_name == "Matters - Open/Smith"


def test_list_matter_labels_scoped_to_root(fake_gmail, settings):
    settings.GMAIL_LABEL_ROOT = "Matters - Open"
    labels = google.list_matter_labels(fake_gmail.account)
    assert [label["short_name"] for label in labels] == ["Doe", "Smith"]

    settings.GMAIL_LABEL_ROOT = ""
    labels = google.list_matter_labels(fake_gmail.account)
    assert len(labels) == 3  # every user label, system ones still excluded


def test_resync_matter_link_and_unlink(matter, fake_gmail):
    fake_gmail.messages = {"m1": gmail_message("m1")}
    stats = google.resync_matter(matter)
    assert stats["created"] == 1

    # Re-link to a label with different contents: stale row dropped.
    fake_gmail.messages = {"m2": gmail_message("m2", thread_id="thread-2")}
    stats = google.resync_matter(matter)
    assert stats["created"] == 1
    assert stats["removed"] == 1
    assert Email.objects.get().gmail_id == "m2"

    # Unlink: all synced rows dropped.
    matter.gmail_label_name = None
    stats = google.resync_matter(matter)
    assert stats["removed"] == 1
    assert Email.objects.count() == 0


# --------------------------------------------------------------------------- #
# Multi-account
# --------------------------------------------------------------------------- #
@pytest.fixture
def second_user(db):
    from apps.accounts.models import CustomUser

    return CustomUser.objects.create(
        username="associate", email="associate@example.com", user_rate=100
    )


def test_same_message_in_two_mailboxes_one_visible(matter, fake_gmail, second_user):
    # Same message (one Message-ID), different per-mailbox gmail ids.
    fake_gmail.messages = {"a1": gmail_message("a1", message_id="<orig@example.com>")}
    other = fake_gmail.connect(second_user, "associate@example.com")
    other.messages = {
        "b1": gmail_message(
            "b1", label_ids=("Label_1",), message_id="<orig@example.com>"
        )
    }

    stats = google.sync(full=True)
    assert stats["created"] == 2  # one provenance row per mailbox
    assert Email.objects.count() == 2
    visible = Email.objects.filter(matter=matter).dedup()
    assert visible.count() == 1
    assert visible.get().account == fake_gmail.account  # first-synced wins


def test_unlabel_in_one_mailbox_keeps_the_others_row(matter, fake_gmail, second_user):
    fake_gmail.messages = {"a1": gmail_message("a1", message_id="<orig@example.com>")}
    other = fake_gmail.connect(second_user, "associate@example.com")
    other.messages = {"b1": gmail_message("b1", message_id="<orig@example.com>")}
    google.sync(full=True)
    assert Email.objects.count() == 2

    # Unlabeled in the primary mailbox only.
    fake_gmail.messages = {}
    fake_gmail.history = [
        {"labelsRemoved": [{"message": {"id": "a1"}, "labelIds": ["Label_1"]}]}
    ]
    stats = google.sync()
    assert stats["removed"] == 1
    remaining = Email.objects.get()
    assert remaining.account == other.account
    assert Email.objects.filter(matter=matter).dedup().count() == 1


def test_account_failure_does_not_block_others(matter, fake_gmail, second_user):
    other = fake_gmail.connect(second_user, "associate@example.com")
    other.messages = {"b1": gmail_message("b1")}

    def boom():
        raise RuntimeError("token revoked")

    fake_gmail.users = boom
    stats = google.sync(full=True)
    assert stats["failed"] == 1
    assert Email.objects.get().account == other.account


def test_per_account_label_resolution(matter, fake_gmail, second_user):
    # The other mailbox uses a different id for the same label name.
    other = fake_gmail.connect(
        second_user,
        "associate@example.com",
        FakeGmailService(
            labels=[{"id": "Label_77", "name": "Matters - Open/Smith", "type": "user"}],
            messages=[gmail_message("b1", label_ids=("Label_77",))],
        ),
    )
    google.sync(full=True)
    email = Email.objects.get()
    assert email.account == other.account
    assert email.matter == matter
    assert email.label_id == "Label_77"
