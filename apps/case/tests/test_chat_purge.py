"""Chat sunset for long-closed matters + auto-unlink on close."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.case.ai.models import Conversation, Message
from apps.case.ai.purge import purge_closed_chats
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding

pytestmark = pytest.mark.django_db


def _matter_with_chat(name, status="Closed", closed_days_ago=200):
    matter = Matter.objects.create(name=name, status=status)
    conversation = Conversation.objects.create(matter=matter, title="Strategy")
    Message.objects.create(conversation=conversation, role="user", content="hi")
    Message.objects.create(conversation=conversation, role="assistant", content="yo")
    # Backdate the entire history so the Closed streak began long ago.
    matter.history.update(history_date=timezone.now() - timedelta(days=closed_days_ago))
    return matter


def test_purges_long_closed_matter_chats():
    matter = _matter_with_chat("Old Closed")
    stats = purge_closed_chats(days=180)
    assert stats == {"matters": 1, "conversations": 1, "messages": 2}
    assert not Conversation.objects.filter(matter=matter).exists()
    assert Message.objects.count() == 0
    # History rows are the bulk; they go too (including deletion stubs).
    assert Message.history.model.objects.count() == 0
    assert Conversation.history.model.objects.count() == 0


def test_recently_closed_and_open_matters_kept():
    _matter_with_chat("Fresh Closed", closed_days_ago=30)
    _matter_with_chat("Still Open", status="Open", closed_days_ago=400)
    stats = purge_closed_chats(days=180)
    assert stats["matters"] == 0
    assert Conversation.objects.count() == 2


def test_reopened_matter_counts_from_latest_close():
    matter = _matter_with_chat("Reopened", closed_days_ago=400)
    # Reopened and re-closed recently: the streak restarts.
    matter.status = "Open"
    matter.save()
    matter.status = "Closed"
    matter.save()
    stats = purge_closed_chats(days=180)
    assert stats["matters"] == 0
    assert Conversation.objects.filter(matter=matter).exists()


def test_dry_run_deletes_nothing():
    _matter_with_chat("Old Closed")
    stats = purge_closed_chats(days=180, dry_run=True)
    assert stats["conversations"] == 1
    assert Conversation.objects.count() == 1
    assert Message.objects.count() == 2


def test_close_unlinks_mirrors():
    matter = Matter.objects.create(
        name="Linked",
        status="Open",
        drive_folder="Linked Folder",
        gmail_label_id="Label_9",
        gmail_label_name="Matters - Open/Linked",
    )
    proceeding = Proceeding.objects.create(
        matter=matter, nickname="Main", drive_folder="Record"
    )

    matter.status = "Closed"
    matter.save()

    matter.refresh_from_db()
    proceeding.refresh_from_db()
    assert matter.drive_folder is None
    assert matter.gmail_label_id is None
    assert matter.gmail_label_name is None
    assert proceeding.drive_folder is None
    assert proceeding.status == "Concluded"
