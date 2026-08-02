"""Sunset AI chat history for long-closed matters.

Chats are working notes, not part of the client file: documents live in
Drive, correspondence in Gmail, notes in the file. Once a matter has been
closed past the retention window the conversations (and their message
history rows, which are the real bulk) are deleted. Nothing regenerates
them: the nightly auto-summary only refreshes Open matters.

Only matter-scoped conversations are touched. Intake and agenda chats are
ephemeral already (one live per owner, deleted on end), and financial or
docket records are never in scope here.
"""

import logging
from datetime import timedelta

from django.utils import timezone

from apps.case.ai.models import Conversation, Message
from apps.matters.models import Matter

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 180


def closed_at(matter):
    """When the matter's current Closed streak began, from its history.

    Walks history newest-first and returns the earliest contiguous Closed
    row, so a matter that was reopened and re-closed counts from the most
    recent closing. None when the history holds no Closed rows.
    """
    closed = None
    for status, when in matter.history.order_by("-history_date").values_list(
        "status", "history_date"
    ):
        if status != "Closed":
            break
        closed = when
    return closed


def purge_closed_chats(days=DEFAULT_RETENTION_DAYS, dry_run=False):
    """Delete chat conversations for matters closed longer than ``days``.

    Deletes the historical rows too (simple-history would otherwise keep
    every message version and add deletion stubs, defeating the purge).
    Returns a stats dict.
    """
    cutoff = timezone.now() - timedelta(days=days)
    stats = {"matters": 0, "conversations": 0, "messages": 0}

    for matter in Matter.objects.filter(status="Closed"):
        conversations = Conversation.objects.filter(matter=matter)
        if not conversations.exists():
            continue
        when = closed_at(matter)
        if when is None or when > cutoff:
            continue

        conversation_ids = list(conversations.values_list("id", flat=True))
        message_count = Message.objects.filter(
            conversation_id__in=conversation_ids
        ).count()

        if not dry_run:
            conversations.delete()  # cascades messages, leaves history stubs
            Message.history.model.objects.filter(
                conversation_id__in=conversation_ids
            ).delete()
            Conversation.history.model.objects.filter(id__in=conversation_ids).delete()

        stats["matters"] += 1
        stats["conversations"] += len(conversation_ids)
        stats["messages"] += message_count
        logger.info(
            "Chat purge: matter %s (closed %s): %s conversations, %s messages%s",
            matter.pk,
            when.date(),
            len(conversation_ids),
            message_count,
            " (dry run)" if dry_run else "",
        )

    return stats


def scheduled_purge_closed_chats():
    """django-q entry point (chat-purge-weekly schedule)."""
    return purge_closed_chats()
