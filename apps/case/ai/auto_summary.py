"""Nightly auto-generated case summaries.

A django-q schedule calls refresh_auto_summaries() each night, which fans out
one task per open matter. Each task asks Gemini Flash for a status summary and
replaces the content of the matter's "Auto Summary" conversation. The thread
never grows: every run leaves exactly one user prompt and one assistant reply.
"""

import logging

from django.db import transaction

from .context import assemble_matter_context_with_selection
from .gemini_client import send_to_gemini

logger = logging.getLogger(__name__)

AUTO_SUMMARY_TITLE = "Auto Summary"
AUTO_SUMMARY_PROMPT = (
    "Provide a structured status summary of this matter as of today. Cover:\n"
    "1. Parties and procedural posture\n"
    "2. Recent developments\n"
    "3. Upcoming deadlines and events\n"
    "4. Open tasks\n"
    "5. Financial posture (billing, settlement)\n"
    "Be concise and factual. Close with anything that needs urgent attention. "
    "If the matter file contains little information, say so briefly rather "
    "than speculating."
)


def refresh_auto_summaries():
    """Nightly dispatcher: queue one refresh task per open matter."""
    from django_q.tasks import async_task

    from apps.matters.models import Matter

    matter_ids = list(Matter.objects.filter(status="Open").values_list("id", flat=True))
    for matter_id in matter_ids:
        async_task(
            "apps.case.ai.auto_summary.refresh_matter_auto_summary",
            matter_id,
            task_name=f"AutoSummary-{matter_id}",
            group="auto_summary",
        )
    logger.info("Auto summary: queued %d open matters", len(matter_ids))
    return len(matter_ids)


def _get_or_create_conversation(matter):
    """Find the matter's system-owned Auto Summary conversation.

    user__isnull distinguishes ours from any human-created conversation that
    happens to share the title (views always set user). There is no unique
    constraint, so consolidate strays if any ever appear.
    """
    from .models import Conversation

    conversations = list(
        Conversation.objects.filter(
            matter=matter, title=AUTO_SUMMARY_TITLE, user__isnull=True
        ).order_by("id")
    )
    if conversations:
        conversation = conversations[0]
        for stray in conversations[1:]:
            stray.delete()
    else:
        conversation = Conversation(matter=matter, title=AUTO_SUMMARY_TITLE, user=None)
    conversation.llm = "gemini-flash"
    conversation.ai_context = "never"
    conversation.vet_citations = False
    conversation.save()
    return conversation


def refresh_matter_auto_summary(matter_id):
    """Per-matter worker: one Gemini Flash call, then replace the thread."""
    from apps.matters.models import Matter

    from .models import Message

    try:
        matter = Matter.objects.get(id=matter_id)
    except Matter.DoesNotExist:
        logger.warning("Auto summary: matter %s no longer exists", matter_id)
        return

    conversation = _get_or_create_conversation(matter)

    try:
        system_context = assemble_matter_context_with_selection(
            matter,
            AUTO_SUMMARY_PROMPT,
            "gemini-flash",
            user=None,
            conversation=conversation,
        )
        text, input_tokens, output_tokens = send_to_gemini(
            system_context=system_context,
            messages=[{"role": "user", "content": AUTO_SUMMARY_PROMPT}],
            model="gemini-2.5-flash",
            conversation_id=conversation.id,
        )
    except Exception:
        logger.exception(
            "Auto summary failed for matter %s; keeping previous summary",
            matter_id,
        )
        return

    if not text or not text.strip():
        logger.warning(
            "Auto summary: empty response for matter %s; keeping previous",
            matter_id,
        )
        return

    text = text.strip()
    with transaction.atomic():
        conversation.messages.all().delete()
        Message.objects.create(
            conversation=conversation,
            role="user",
            content=AUTO_SUMMARY_PROMPT,
            user=None,
        )
        Message.objects.create(
            conversation=conversation,
            role="assistant",
            content=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        conversation.summary = text[:500]
        conversation.save()
