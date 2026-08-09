"""Nightly auto-generated AI threads: case summary and litigation agenda.

A django-q schedule calls refresh_auto_summaries() each night, which fans out
one task per open matter. Each matter refreshes two system-owned conversations
with Gemini Pro:

- "Auto Summary": the substantive issues — factual nexus, legal issues in
  controversy, positions, key evidence.
- "Auto Agenda": a litigation plan — next steps, timeline to resolution,
  strategic goals. Runs after the summary so the fresh summary is in its
  context (both threads are ai_context="always" reference conversations).

Each refresh replaces the thread's content: one user prompt and one assistant
reply. Attorneys can converse in the thread during the day through the normal
chat UI; that discussion is folded into the next refresh as controlling
guidance, then the thread resets.

The first run for a matter uses the full context-selection pipeline. Later
runs are incremental: the previous version plus only the records added or
changed since it was written. A large delta, or a thread generated under a
since-retired prompt, rebuilds from the full record.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction

from .context import (
    assemble_matter_context_with_selection,
    collect_context_items,
    format_contacts,
    format_events,
    format_matter_overview,
    format_proceedings,
    format_settlement,
    format_tasks,
    get_importance_label,
    load_legal_prompt,
)
from .gemini_client import send_to_gemini

logger = logging.getLogger(__name__)

# Picker key and Gemini model ID (see LLM_CHOICES and GEMINI_MODELS)
LLM_KEY = "gemini-pro-latest"
GEMINI_MODEL_ID = "gemini-pro-latest"

# Records added or edited while the previous run was generating have
# timestamps just before the previous assistant message; look back a little
# past it so they are never skipped. Seeing an item twice is harmless.
CUTOFF_MARGIN = timedelta(minutes=10)

# Above this many characters of changed records, incremental context stops
# being an efficiency win; rebuild through the full selection pipeline, which
# knows how to budget.
INCREMENTAL_FALLBACK_CHARS = 300_000

AUTO_SUMMARY_TITLE = "Auto Summary"
AUTO_AGENDA_TITLE = "Auto Agenda"

SUMMARY_STRUCTURE = (
    "1. Core factual nexus: the operative events and circumstances from which "
    "the case arises, in narrative form\n"
    "2. Legal issues in controversy: each claim or defense and the specific "
    "elements or questions actually in dispute\n"
    "3. Each party's position on the disputed issues\n"
    "4. Key evidence bearing on each disputed issue\n"
)

SUMMARY_POSTURE_NOTE = (
    "State the case's current phase (active litigation, negotiation, awaiting "
    "a sale or ruling, monitoring, wind-down) as part of the procedural "
    "posture; the time entries in the context show the work actually being "
    "performed and are the best evidence of the current phase. Do not "
    "summarize billing amounts, scheduling, or administrative status. "
)

AUTO_SUMMARY_PROMPT = (
    "Provide a summary of the substantive issues in this matter. Cover:\n"
    + SUMMARY_STRUCTURE
    + "Be concise and factual, and ground every point in the case record. "
    + SUMMARY_POSTURE_NOTE
    + "If the matter file contains little information, say so briefly rather "
    "than speculating."
)

AUTO_SUMMARY_UPDATE_PROMPT = (
    "Update the summary of the substantive issues in this matter. The context "
    "contains the previous summary, the records and time entries added or "
    "changed since it was written, and any attorney feedback on the previous "
    "version. Produce a complete, standalone replacement summary with the "
    "same structure:\n"
    + SUMMARY_STRUCTURE
    + "Carry forward what still holds from the previous summary, incorporate "
    "the new records, follow the attorney guidance, and drop anything the new "
    "records supersede. Be concise and factual, and ground every point in the "
    "case record. " + SUMMARY_POSTURE_NOTE
)

AGENDA_STRUCTURE = (
    "1. Next steps: the concrete actions to take now, in priority order, and "
    "what each accomplishes\n"
    "2. Timeline to resolution: the realistic path from the current posture "
    "to final resolution, phase by phase\n"
    "3. Key strategic goals: what must be secured to bring about a successful "
    "resolution for our client, and how each will be won\n"
)

AGENDA_POSTURE_NOTE = (
    "Match the plan to the case's actual phase. The tasks, events, and time "
    "entries in the context show what has already been done and what is "
    "actually pending; treat them as the ground truth of the current posture. "
    "If the main objectives are already secured and the matter is in a "
    "monitoring or holding posture, say so plainly and confine the plan to "
    "what to watch, the triggers that would require action, and the steps to "
    "close the matter. Do not invent litigation activity for its own sake. "
)

AUTO_AGENDA_PROMPT = (
    "Acting as a legal analyst and advocate for our client, build a "
    "litigation plan for this matter. Analyze the record deeply before "
    "answering. Cover:\n"
    + AGENDA_STRUCTURE
    + AGENDA_POSTURE_NOTE
    + "Ground the plan in the case record, anticipate the opposing parties' "
    "likely moves, and be candid about weaknesses and risks. If the matter "
    "file contains little information, say so briefly rather than speculating."
)

AUTO_AGENDA_UPDATE_PROMPT = (
    "Update the litigation plan for this matter. The context contains the "
    "previous plan, the records and time entries added or changed since it "
    "was written, and any attorney feedback on the previous version. Acting "
    "as a legal analyst and advocate for our client, produce a complete, "
    "standalone replacement plan with the same structure:\n"
    + AGENDA_STRUCTURE
    + AGENDA_POSTURE_NOTE
    + "Carry forward what still holds from the previous plan, incorporate the "
    "new records, follow the attorney guidance, and drop steps that are "
    "completed or superseded. Anticipate the opposing parties' likely moves "
    "and be candid about weaknesses and risks."
)


@dataclass(frozen=True)
class ThreadSpec:
    title: str
    initial_prompt: str
    update_prompt: str


SUMMARY_SPEC = ThreadSpec(
    title=AUTO_SUMMARY_TITLE,
    initial_prompt=AUTO_SUMMARY_PROMPT,
    update_prompt=AUTO_SUMMARY_UPDATE_PROMPT,
)
AGENDA_SPEC = ThreadSpec(
    title=AUTO_AGENDA_TITLE,
    initial_prompt=AUTO_AGENDA_PROMPT,
    update_prompt=AUTO_AGENDA_UPDATE_PROMPT,
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

## Current Tasks
{tasks}

## Events (upcoming, plus recent past)
{events}

## Previous Version of the {title} (generated {previous_date})
{previous_content}

## Records Added or Changed Since {previous_date}
{new_items}

## Time Entries Logged Since {previous_date}
Work actually performed since the previous version; strong evidence of the
case's current phase.

{new_time_entries}
"""

FEEDBACK_TEMPLATE = """

## Attorney Feedback on the Previous Version
After the previous version was generated, the firm's attorneys discussed it
in this thread. Their direction is controlling guidance; follow it unless the
case record contradicts it.

{discussion}
"""


def refresh_auto_summaries(force_full=False):
    """Nightly dispatcher: queue one refresh task per open matter."""
    from django_q.tasks import async_task

    from apps.matters.models import Matter

    matter_ids = list(Matter.objects.filter(status="Open").values_list("id", flat=True))
    for matter_id in matter_ids:
        async_task(
            "apps.case.ai.auto_summary.refresh_matter_auto_summary",
            matter_id,
            force_full,
            task_name=f"AutoSummary-{matter_id}",
            group="auto_summary",
        )
    logger.info("Auto summary: queued %d open matters", len(matter_ids))
    return len(matter_ids)


def refresh_auto_summaries_full():
    """Rebuild every thread from the full record.

    Guards against quality drift from summaries compounding on summaries.
    """
    return refresh_auto_summaries(force_full=True)


def scheduled_refresh_auto_summaries():
    """Schedule target for the nightly incremental run. Prod only.

    The dev database is overwritten from prod nightly, so dev inherits
    prod's Schedule rows and would duplicate the whole spend. On-demand
    runs (the run_auto_summaries command) bypass this guard.
    """
    if settings.ENV != "prod":
        logger.info("Auto summary: scheduled run skipped (ENV=%s)", settings.ENV)
        return 0
    return refresh_auto_summaries()


def scheduled_refresh_auto_summaries_full():
    """Schedule target for the weekly (early Monday) full rebuild. Prod only."""
    if settings.ENV != "prod":
        logger.info("Auto summary: scheduled rebuild skipped (ENV=%s)", settings.ENV)
        return 0
    return refresh_auto_summaries_full()


def refresh_matter_auto_summary(matter_id, force_full=False):
    """Refresh the Auto Summary thread, then queue the Auto Agenda refresh.

    The agenda runs as its own task so each Gemini Pro call gets the full
    qcluster timeout, and after the summary so the fresh summary is in the
    agenda's context.
    """
    from django_q.tasks import async_task

    from apps.matters.models import Matter

    try:
        matter = Matter.objects.get(id=matter_id)
    except Matter.DoesNotExist:
        logger.warning("Auto summary: matter %s no longer exists", matter_id)
        return

    _refresh_thread(matter, SUMMARY_SPEC, force_full=force_full)
    async_task(
        "apps.case.ai.auto_summary.refresh_matter_auto_agenda",
        matter_id,
        force_full,
        task_name=f"AutoAgenda-{matter_id}",
        group="auto_summary",
    )


def refresh_matter_auto_agenda(matter_id, force_full=False):
    """Refresh the Auto Agenda thread."""
    from apps.matters.models import Matter

    try:
        matter = Matter.objects.get(id=matter_id)
    except Matter.DoesNotExist:
        logger.warning("Auto agenda: matter %s no longer exists", matter_id)
        return

    _refresh_thread(matter, AGENDA_SPEC, force_full=force_full)


def _get_or_create_conversation(matter, title):
    """Find the matter's system-owned conversation with this title.

    user__isnull distinguishes ours from any human-created conversation that
    happens to share the title (views always set user). There is no unique
    constraint, so consolidate strays if any ever appear.
    """
    from .models import Conversation

    conversations = list(
        Conversation.objects.filter(
            matter=matter, title=title, user__isnull=True
        ).order_by("id")
    )
    if conversations:
        conversation = conversations[0]
        for stray in conversations[1:]:
            stray.delete()
    else:
        conversation = Conversation(matter=matter, title=title, user=None)
    conversation.llm = LLM_KEY
    conversation.ai_context = "always"
    conversation.vet_citations = False
    conversation.save()
    return conversation


def _format_discussion(messages):
    """Render thread discussion (everything after the initial pair)."""
    lines = []
    for msg in messages:
        if msg.role == "user":
            name = msg.user.get_full_name() if msg.user else "Attorney"
            lines.append(f"**{name}:** {msg.content}")
        else:
            lines.append(f"**Assistant:** {msg.content}")
    return "\n\n".join(lines)


def _format_new_time_entries(matter, cutoff):
    """Time entries added or edited since the cutoff, newest first."""
    from apps.activity.time.models import TimeEntry

    entries = (
        TimeEntry.objects.filter(matter=matter, updated_at__gte=cutoff)
        .select_related("user")
        .order_by("-date")[:50]
    )
    if not entries:
        return "No time entries logged since the previous version."

    lines = []
    for entry in entries:
        user_name = entry.user.get_full_name() if entry.user else "Unknown"
        lines.append(
            f"- [{entry.date}] {entry.actions} — {entry.hours}h by {user_name}"
        )
    return "\n".join(lines)


def build_incremental_context(matter, conversation, previous, spec):
    """System context for an update run: previous version + delta since it.

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
            "Auto thread %r: %d chars of new records for matter %s, "
            "falling back to full context",
            spec.title,
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
        new_items = "No records have been added or changed since the previous version."

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
        tasks=format_tasks(matter),
        events=format_events(matter),
        title=spec.title,
        previous_date=previous.created_at.strftime("%b %d, %Y"),
        previous_content=previous.content,
        new_items=new_items,
        new_time_entries=_format_new_time_entries(matter, cutoff),
    )

    return f"{legal_prompt}\n\n---\n{matter_context}"


def _refresh_thread(matter, spec, force_full=False):
    """Regenerate one auto thread: one Gemini Pro call, then replace it."""
    from .models import Message

    conversation = _get_or_create_conversation(matter, spec.title)
    messages = list(conversation.messages.order_by("created_at"))

    # The thread's canonical shape is [our prompt, the generated reply,
    # then any attorney discussion]. The baseline for an incremental run is
    # the ORIGINAL reply (messages[1]), not later discussion replies.
    baseline = None
    discussion = []
    if len(messages) >= 2 and messages[0].role == "user":
        discussion = messages[2:]
        if force_full:
            pass
        elif messages[0].content in (spec.initial_prompt, spec.update_prompt):
            baseline = messages[1]
        else:
            # Generated under an older prompt that covered different ground;
            # an incremental pass can't repair that baseline. Rebuild from
            # the full record; the discussion still counts as guidance.
            logger.info(
                "Auto thread %r: prompt changed for matter %s, "
                "rebuilding from full context",
                spec.title,
                matter.id,
            )

    try:
        system_context = None
        prompt = spec.update_prompt
        if baseline:
            system_context = build_incremental_context(
                matter, conversation, baseline, spec
            )
        if system_context is None:
            prompt = spec.initial_prompt
            system_context = assemble_matter_context_with_selection(
                matter,
                spec.initial_prompt,
                LLM_KEY,
                user=None,
                conversation=conversation,
                # The nightly summary describes the matter record; firm-library
                # reference notes would pollute it and inflate the run.
                include_library=False,
            )
        if discussion:
            system_context += FEEDBACK_TEMPLATE.format(
                discussion=_format_discussion(discussion)
            )
        text, input_tokens, output_tokens = send_to_gemini(
            system_context=system_context,
            messages=[{"role": "user", "content": prompt}],
            model=GEMINI_MODEL_ID,
            conversation_id=conversation.id,
        )
    except Exception:
        logger.exception(
            "Auto thread %r failed for matter %s; keeping previous version",
            spec.title,
            matter.id,
        )
        return

    if not text or not text.strip():
        logger.warning(
            "Auto thread %r: empty response for matter %s; keeping previous",
            spec.title,
            matter.id,
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
