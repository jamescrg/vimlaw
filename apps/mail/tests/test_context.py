from datetime import timedelta

import pytest
from django.utils import timezone

from apps.case.ai.context import collect_context_items
from apps.case.ai.selector import _parse_selector_response, build_manifest
from apps.mail.models import Email

pytestmark = pytest.mark.django_db


def make_email(matter, gmail_id, thread_id="thread-1", ai_context="auto", **kwargs):
    defaults = {
        "sender": "alice@example.com",
        "recipients": "bob@example.com",
        "subject": "Settlement discussion",
        "date": timezone.now(),
        "body_text": "We propose fifty thousand dollars.",
    }
    defaults.update(kwargs)
    return Email.objects.create(
        matter=matter,
        gmail_id=gmail_id,
        thread_id=thread_id,
        ai_context=ai_context,
        **defaults,
    )


def test_always_emails_grouped_by_thread(matter):
    make_email(matter, "m1", ai_context="always", importance=3)
    make_email(matter, "m2", ai_context="always", importance=5)
    make_email(matter, "m3", thread_id="thread-2", ai_context="always")

    items = [i for i in collect_context_items(matter) if i.item_type == "email"]
    assert len(items) == 2
    two_msg = next(i for i in items if "2 messages" in i.content)
    assert two_msg.importance == 5  # max within the thread
    assert "Settlement discussion" in two_msg.content


def test_auto_emails_left_to_selector(matter):
    make_email(matter, "m1", ai_context="auto")
    assert not any(i.item_type == "email" for i in collect_context_items(matter))
    assert any(
        i.item_type == "email" for i in collect_context_items(matter, include_auto=True)
    )


def test_never_emails_excluded(matter):
    make_email(matter, "m1", ai_context="never")
    items = collect_context_items(matter, include_auto=True)
    assert not any(i.item_type == "email" for i in items)


def test_since_renders_only_new_messages(matter):
    old = make_email(matter, "m1", ai_context="always", body_text="Old message")
    cutoff = timezone.now() + timedelta(minutes=5)
    Email.objects.filter(pk=old.pk).update(updated_at=timezone.now())

    new = make_email(matter, "m2", ai_context="always", body_text="New message")
    Email.objects.filter(pk=new.pk).update(updated_at=cutoff + timedelta(minutes=5))

    items = [
        i for i in collect_context_items(matter, since=cutoff) if i.item_type == "email"
    ]
    assert len(items) == 1
    assert "New message" in items[0].content
    assert "Old message" not in items[0].content
    assert "thread continues earlier" in items[0].content


def test_since_skips_threads_with_no_new_mail(matter):
    old = make_email(matter, "m1", ai_context="always")
    Email.objects.filter(pk=old.pk).update(updated_at=timezone.now())
    cutoff = timezone.now() + timedelta(minutes=5)

    items = [
        i for i in collect_context_items(matter, since=cutoff) if i.item_type == "email"
    ]
    assert items == []


def test_manifest_one_item_per_thread(matter):
    make_email(matter, "m1", body_text="one two three")
    make_email(matter, "m2", body_text="four five")
    make_email(matter, "m3", thread_id="thread-2")

    manifest, content_map = build_manifest(matter)
    email_items = [i for i in manifest if i.item_type == "email"]
    assert len(email_items) == 2

    thread_item = next(i for i in email_items if "2 messages" in i.category)
    assert thread_item.word_count == 5
    assert thread_item.name == "Settlement discussion"
    content = content_map[("email", thread_item.item_id)]
    assert "one two three" in content
    assert "four five" in content


def test_attachment_text_joins_thread_context(matter):
    from apps.mail.models import EmailAttachment

    email = make_email(matter, "m1", ai_context="always")
    EmailAttachment.objects.create(
        email=email,
        filename="lease.pdf",
        size=5000,
        text="The lease term is five years.",
        extract_status="extracted",
    )

    items = [i for i in collect_context_items(matter) if i.item_type == "email"]
    assert "Attachment text: lease.pdf" in items[0].content
    assert "The lease term is five years." in items[0].content

    # Selector word count includes attachment text.
    email.ai_context = "auto"
    email.save(update_fields=["ai_context"])
    manifest, _ = build_manifest(matter)
    item = next(i for i in manifest if i.item_type == "email")
    assert item.word_count == len("We propose fifty thousand dollars.".split()) + len(
        "The lease term is five years.".split()
    )


def test_selector_response_accepts_email_type():
    keys = _parse_selector_response(
        '{"selected": [{"type": "email", "id": 7}, {"type": "bogus", "id": 1}]}'
    )
    assert keys == [("email", 7)]
