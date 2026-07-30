import pytest

import apps.mail.google as google
from apps.mail.models import Email, GmailSyncState

from .conftest import gmail_message, http_error

pytestmark = pytest.mark.django_db


def _state():
    return GmailSyncState.objects.get(pk=1)


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
    # Cursor captured from the profile before listing.
    assert _state().history_id == "2000"


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
    assert stats["missing_labels"] == ["Label_1"]
    assert _state().missing_labels == ["Label_1"]


def test_label_rename_refreshes_snapshot(matter, fake_gmail):
    fake_gmail.labels = [
        {"id": "Label_1", "name": "Matters - Open/Smith (new)", "type": "user"}
    ]
    google.sync(full=True)
    matter.refresh_from_db()
    assert matter.gmail_label_name == "Matters - Open/Smith (new)"


def test_list_matter_labels_scoped_to_root(fake_gmail, settings):
    settings.GMAIL_LABEL_ROOT = "Matters - Open"
    labels = google.list_matter_labels()
    assert [label["short_name"] for label in labels] == ["Doe", "Smith"]

    settings.GMAIL_LABEL_ROOT = ""
    labels = google.list_matter_labels()
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
    matter.gmail_label_id = None
    stats = google.resync_matter(matter)
    assert stats["removed"] == 1
    assert Email.objects.count() == 0
