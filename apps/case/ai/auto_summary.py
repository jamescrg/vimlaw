"""Nightly auto-generated case summaries.

A django-q schedule calls refresh_auto_summaries() each night, which fans out
one task per open matter. Each task asks Gemini Flash for a status summary and
replaces the content of the matter's "Auto Summary" conversation. The thread
never grows: every run leaves exactly one user prompt and one assistant reply.

The first run for a matter uses the full context-selection pipeline. Later
runs are incremental: the previous summary plus only the records added or
changed since it was written, so the nightly query stays small. A large delta
falls back to the full pipeline, which knows how to budget context.

The conversation is ai_context="always", so the latest summary is inlined
into every other chat's context as a reference conversation.
"""

import logging
from datetime import timedelta

from django.db import transaction

from .context import (
    assemble_matter_context_with_selection,
    collect_context_items,
    format_contacts,
    format_matter_overview,
    format_proceedings,
    format_settlement,
    get_importance_label,
    load_legal_prompt,
)
from .gemini_client import send_to_gemini

logger = logging.getLogger(__name__)

AUTO_SUMMARY_TITLE = "Auto Summary"

# Records added or edited while the previous run was generating have
# timestamps just before the previous assistant message; look back a little
# past it so they are never skipped. Seeing an item twice is harmless.
CUTOFF_MARGIN = timedelta(minutes=10)

# Above this many characters of changed records, incremental context stops
# being an efficiency win; rebuild through the full selection pipeline, which
# knows how to budget.
INCREMENTAL_FALLBACK_CHARS = 300_000

SUMMARY_STRUCTURE = (
    "1. Core factual nexus: the operative events and circumstances from which "
    "the case arises, in narrative form\n"
    "2. Legal issues in controversy: each claim or defense and the specific "
    "elements or questions actually in dispute\n"
    "3. Each party's position on the disputed issues\n"
    "4. Key evidence bearing on each disputed issue\n"
)

AUTO_SUMMARY_PROMPT = (
    "Provide a summary of the substantive issues in this matter. Cover:\n"
    + SUMMARY_STRUCTURE
    + "Be concise and factual, and ground every point in the case record. Do "
    "not cover scheduling, billing, or administrative status. If the matter "
    "file contains little information, say so briefly rather than speculating."
)

AUTO_SUMMARY_UPDATE_PROMPT = (
    "Update the summary of the substantive issues in this matter. The context "
    "contains the previous summary and the records added or changed since it "
    "was written. Produce a complete, standalone replacement summary with the "
    "same structure:\n"
    + SUMMARY_STRUCTURE
    + "Carry forward what still holds from the previous summary, incorporate "
    "the new records, and drop anything the new records supersede. Be concise "
    "and factual, and ground every point in the case record. Do not cover "
    "scheduling, billing, or administrative status."
)

INCREMENTAL_CONTEXT_TEMPLATE = """
## Current Matter: {matter_name}

## Matter Overview
{matter_overview}

## Contacts & Parties
{contacts}

## Court Proceedings
{proceedings}

## Settlement Information
{settlement}

## Previous Summary (generated {previous_date})
{previous_summary}

## Records Added or Changed Since {previous_date}
{new_items}
"""


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
    conversation.ai_context = "always"
    conversation.vet_citations = False
    conversation.save()
    return conversation


def build_incremental_context(matter, conversation, previous):
    """System context for an update run: previous summary + delta since it.

    Returns None when the delta is too large to be worth an incremental pass;
    the caller should fall back to the full selection pipeline.
    """
    from apps.settings.models import Firm

    cutoff = previous.created_at - CUTOFF_MARGIN
    items = collect_context_items(
        matter, current_conversation=conversation, since=cutoff, include_auto=True
    )

    total_chars = sum(len(item.content) for item in items)
    if total_chars > INCREMENTAL_FALLBACK_CHARS:
        logger.info(
            "Auto summary: %d chars of new records for matter %s, "
            "falling back to full context",
            total_chars,
            matter.id,
        )
        return None

    if items:
        new_items = "\n\n".join(
            f"[{get_importance_label(item.importance)}] {item.content}"
            for item in items
        )
    else:
        new_items = "No records have been added or changed since the previous summary."

    company = Firm.objects.first()
    jurisdiction = (
        matter.jurisdiction
        or (company.jurisdiction if company else "")
        or "United States common law"
    )
    legal_prompt = load_legal_prompt(jurisdiction=jurisdiction)

    matter_context = INCREMENTAL_CONTEXT_TEMPLATE.format(
        matter_name=matter.name,
        matter_overview=format_matter_overview(matter),
        contacts=format_contacts(matter),
        proceedings=format_proceedings(matter),
        settlement=format_settlement(matter),
        previous_date=previous.created_at.strftime("%b %d, %Y"),
        previous_summary=previous.content,
        new_items=new_items,
    )

    return f"{legal_prompt}\n\n---\n{matter_context}"


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
    previous = (
        conversation.messages.filter(role="assistant").order_by("created_at").last()
    )

    # A baseline written under an older prompt covers different ground, so an
    # incremental pass can't repair it; rebuild from the full record once and
    # incremental runs resume the night after.
    stored_prompt = (
        conversation.messages.filter(role="user").order_by("created_at").last()
    )
    if stored_prompt and stored_prompt.content not in (
        AUTO_SUMMARY_PROMPT,
        AUTO_SUMMARY_UPDATE_PROMPT,
    ):
        logger.info(
            "Auto summary: prompt changed for matter %s, rebuilding from full context",
            matter_id,
        )
        previous = None

    try:
        system_context = None
        prompt = AUTO_SUMMARY_UPDATE_PROMPT
        if previous:
            system_context = build_incremental_context(matter, conversation, previous)
        if system_context is None:
            prompt = AUTO_SUMMARY_PROMPT
            system_context = assemble_matter_context_with_selection(
                matter,
                AUTO_SUMMARY_PROMPT,
                "gemini-flash",
                user=None,
                conversation=conversation,
            )
        text, input_tokens, output_tokens = send_to_gemini(
            system_context=system_context,
            messages=[{"role": "user", "content": prompt}],
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
            content=prompt,
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
