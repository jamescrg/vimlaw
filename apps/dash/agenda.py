"""Suggested agendas: a dash-launched AI chat that plans the user's work.

Gemini Pro reviews the firm's open matters, active tasks, upcoming events,
recent time entries, and open intakes, and suggests an agenda - defaulting
to the day ahead, expandable to week or month by asking. Admins get the
whole team's workload and cross-user suggestions; everyone else plans
their own. At the user's explicit direction the AI emits a fenced
create-tasks block that this module parses into real Task rows (any
user may assign a task to any teammate). One live
agenda conversation per user, resumable until discarded; opening with
none live auto-generates the daily agenda.

Reuses the case/intake chat machinery: Conversation/Message, the cache
status protocol polled by case:ai-status, and the shared message
templates.
"""

import json
import logging
import re
import threading
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.access import filter_matters_for_user
from apps.accounts.models import CustomUser
from apps.activity.time.models import TimeEntry
from apps.calendar.models import Event
from apps.case.ai.models import Conversation, Message
from apps.case.ai.status import (
    FINAL_TTL,
    RUNNING_TTL,
    RunHeartbeat,
    status_cache,
)
from apps.intakes.models import Intake, Note
from apps.matters.models import Matter
from apps.tasks.constants import ACTIVE_STATUSES
from apps.tasks.models import Task

logger = logging.getLogger(__name__)

AGENDA_MODEL = "gemini-pro-latest"

AGENDA_CONTEXT_LIMIT = 80_000
AUTO_THREAD_CONTEXT_LIMIT = 400_000
TIME_ENTRY_DAYS = 14
EVENT_LOOKAHEAD_DAYS = 30

AUTO_START_MESSAGE = "Suggest my agenda for the day ahead."

AGENDA_PREAMBLE = """You are the firm's agenda assistant. From the workload data below, suggest
what to work on - a prioritized, concrete agenda. Default to the day
ahead; expand to a week or a month only when asked.

How to weigh the data:
- Event dates are hard deadlines. Task due dates are generally soft -
  treat them as intentions, not commitments.
- A matter's work status may be out of date; recent time entries are
  fresher evidence of where things actually stand.
- Flag stale intakes (many days since the last note) that need a touch.
- Balance attention across matters; note anything that looks neglected.

Keep replies concise and agenda-shaped: short prioritized lists with a
line of reasoning where it helps, not essays.
{admin_note}
STAY IN YOUR LANE. This chat plans workload; it does not analyze case
merits. When the user starts discussing the substance of a specific
matter or intake, give at most a one-line acknowledgment, point out that
the dedicated chat has the full context (documents, notes, filings) this
window lacks, and offer its markdown link from the data below, e.g.
[Open the Smith chat](/case/12/ai/conversations/new/). Never attempt
substantive legal analysis here.

CREATING TASKS. Only when the user explicitly directs you to create
tasks, end your reply with exactly one fenced block in this form:

```create-tasks
[{{"description": "<4-200 chars>", "matter": "<exact matter name or null>", "user": "<team member full name or null>", "due": "YYYY-MM-DD or null", "importance": 4}}]
```

Suggesting an agenda item is NOT direction to create a task - never emit
the block unprompted. Importance is the firm's 1-7 scale (4 = Normal).
"""

ADMIN_NOTE = """
The requesting user is an ADMIN: the data covers the whole team. When
asked (or when clearly useful), suggest what individual team members
should focus on and flag workload imbalances - name names.
"""


def _matter_label(matter):
    return matter.name or f"Matter {matter.id}"


def _agenda_context(user):
    """The workload data sections. Admins see everyone; others see their
    own tasks and time (plus unassigned items) against the firm's matters."""
    today = timezone.localdate()
    parts = []

    matters = (
        filter_matters_for_user(
            Matter.objects.filter(status__in=["Pending", "Open"]), user
        )
        .select_related("practice_area", "client")
        .order_by("name")
    )
    parts.append("OPEN MATTERS (chat links go to each matter's case chat)")
    for m in matters:
        parts.append(
            f"- {_matter_label(m)} [{m.status}]"
            f" | area: {m.practice_area.name if m.practice_area else ''}"
            f" | client: {m.client.name if m.client else ''}"
            f" | description: {m.description or ''}"
            f" | work status: {m.work_status or 'not set'}"
            f" | chat: /case/{m.id}/ai/conversations/new/"
        )

    tasks = Task.objects.filter(status__in=ACTIVE_STATUSES).select_related(
        "user", "matter"
    )
    if not user.is_admin:
        tasks = tasks.filter(Q(user=user) | Q(user__isnull=True))
    parts.append("\nACTIVE TASKS (due dates are generally soft)")
    for t in tasks.order_by("date_due", "-importance"):
        parts.append(
            f"- {t.description}"
            f" | matter: {_matter_label(t.matter) if t.matter else 'Admin'}"
            f" | due: {t.date_due or 'none'}"
            f" | importance: {t.importance}"
            f" | status: {t.status}"
            f" | assigned: {t.user.full_name if t.user else 'unassigned'}"
        )

    events = Event.objects.filter(
        status="Pending",
        date__lte=today + timedelta(days=EVENT_LOOKAHEAD_DAYS),
    ).select_related("assigned_to", "matter")
    if not user.is_admin:
        events = events.filter(Q(assigned_to=user) | Q(assigned_to__isnull=True))
    parts.append("\nEVENTS (pending; overdue and next 30 days; hard dates)")
    for e in events.order_by("date", "start_time"):
        overdue = " OVERDUE" if e.date and e.date < today else ""
        parts.append(
            f"- {e.date}{overdue} {e.start_time or ''} | {e.description or ''}"
            f" | matter: {_matter_label(e.matter) if e.matter else ''}"
            f" | type: {e.event_type or ''}"
            f" | assigned: {e.assigned_to.full_name if e.assigned_to else 'Firm'}"
        )

    entries = TimeEntry.objects.filter(
        date__gte=today - timedelta(days=TIME_ENTRY_DAYS)
    ).select_related("user", "matter")
    if not user.is_admin:
        entries = entries.filter(user=user)
    parts.append(
        f"\nRECENT TIME ENTRIES (last {TIME_ENTRY_DAYS} days; what was actually worked)"
    )
    for entry in entries.order_by("-date"):
        parts.append(
            f"- {entry.date} | {entry.user.full_name if entry.user else ''}"
            f" | {_matter_label(entry.matter) if entry.matter else ''}"
            f" | {entry.hours}h | {entry.actions or ''}"
        )

    intakes = Intake.objects.filter(status__in=["Open", "Pending"]).select_related(
        "practice_area"
    )
    parts.append(
        "\nOPEN INTAKES (prospective clients; flag stale ones;"
        " chat links go to each intake's chat)"
    )
    for i in intakes.order_by("-date"):
        last_note = Note.objects.filter(intake=i).order_by("-date", "-id").first()
        last_activity = (last_note.date if last_note else None) or i.date
        stale_days = (today - last_activity).days if last_activity else "unknown"
        parts.append(
            f"- {i.name} [{i.status}] | opened: {i.date}"
            f" | area: {i.practice_area.name if i.practice_area else ''}"
            f" | importance: {i.importance}"
            f" | days since last activity: {stale_days}"
            f" | chat: /intakes/{i.id}/chat/"
        )

    return "\n".join(parts)[:AGENDA_CONTEXT_LIMIT]


def _auto_thread_section(user):
    """Full text of each visible open matter's nightly Auto Summary and
    Auto Agenda: the strategic picture behind the raw workload data."""
    from apps.case.ai.auto_summary import AUTO_AGENDA_TITLE, AUTO_SUMMARY_TITLE

    matters = filter_matters_for_user(
        Matter.objects.filter(status="Open"), user
    ).order_by("name")
    threads = (
        Conversation.objects.filter(
            matter__in=matters,
            title__in=[AUTO_SUMMARY_TITLE, AUTO_AGENDA_TITLE],
            user__isnull=True,
        )
        .select_related("matter")
        .prefetch_related("messages")
    )
    by_matter = {}
    for conv in threads:
        replies = [m.content for m in conv.messages.all() if m.role == "assistant"]
        if replies:
            by_matter.setdefault(conv.matter_id, []).append((conv.title, replies[0]))

    parts = [
        "\nPER-MATTER CASE SUMMARIES AND LITIGATION PLANS"
        " (auto-generated nightly; use them to weigh what matters most)"
    ]
    for m in matters:
        if m.id not in by_matter:
            continue
        parts.append(f"\n### {_matter_label(m)}")
        for title, content in sorted(by_matter[m.id]):
            parts.append(f"[{title}]\n{content}")
    return "\n".join(parts)[:AUTO_THREAD_CONTEXT_LIMIT]


def _agenda_system_prompt(user, thorough=False):
    from apps.case.ai.context import build_request_info

    preamble = AGENDA_PREAMBLE.format(admin_note=ADMIN_NOTE if user.is_admin else "")
    sections = [build_request_info(user), preamble, "---", _agenda_context(user)]
    if thorough:
        sections.append(_auto_thread_section(user))
    return "\n".join(sections)


# ── Task creation ────────────────────────────────────────────────────────────

TASK_BLOCK_RE = re.compile(r"```create-tasks\s*\n(.*?)```", re.DOTALL)


def _create_task_from_entry(entry, requesting_user):
    from apps.tasks.services import create_task_from_ai_entry

    return create_task_from_ai_entry(entry, requesting_user)


def _apply_task_blocks(response_text, requesting_user):
    """Create Tasks from any create-tasks blocks, replacing each block
    with a confirmation list. A malformed block is left as text and
    creates nothing."""

    def replace(match):
        try:
            entries = json.loads(match.group(1).strip())
            if not isinstance(entries, list):
                raise ValueError("create-tasks block is not a list")
        except (ValueError, TypeError):
            logger.warning("Unparseable create-tasks block left in place")
            return match.group(0)

        lines = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            task = _create_task_from_entry(entry, requesting_user)
            if task is not None:
                lines.append(
                    f"- Created task: **{task.description}**"
                    f" ({task.matter.name if task.matter else 'Admin'}"
                    f", due {task.date_due or 'none'}"
                    f", for {task.user.full_name})"
                )
        return "\n".join(lines) if lines else "(no tasks created)"

    return TASK_BLOCK_RE.sub(replace, response_text)


# ── Overnight plans ──────────────────────────────────────────────────────────


def refresh_daily_plans():
    """Nightly dispatcher: queue one plan generation per active user.

    Scheduled after the per-matter auto threads refresh, so each plan can
    draw on that night's summaries and litigation agendas.
    """
    from django_q.tasks import async_task

    user_ids = list(
        CustomUser.objects.filter(is_active=True).values_list("id", flat=True)
    )
    for user_id in user_ids:
        async_task(
            "apps.dash.agenda.generate_overnight_plan",
            user_id,
            task_name=f"DailyPlan-{user_id}",
            group="daily_plan",
        )
    logger.info("Daily plans: queued %d users", len(user_ids))
    return len(user_ids)


def scheduled_refresh_daily_plans():
    """Schedule target. Prod only: the dev DB is overwritten from prod
    nightly, so dev inherits prod's Schedule rows and would double the
    spend. On-demand runs (run_daily_plans) bypass this guard."""
    from django.conf import settings

    if settings.ENV != "prod":
        logger.info("Daily plans: scheduled run skipped (ENV=%s)", settings.ENV)
        return 0
    return refresh_daily_plans()


PLAN_FEEDBACK_TEMPLATE = """

YESTERDAY'S PLAN AND THE TEAM'S FEEDBACK ON IT
The previous plan is below, followed by the discussion the user had in
that thread. The user's direction is controlling guidance for today's
plan - honor standing preferences (scheduling habits, priorities,
matters to leave alone) against the current workload data above.

[Previous plan]
{previous_plan}

[Discussion]
{discussion}
"""


def _plan_feedback(user):
    """Yesterday's plan + discussion, when the user actually conversed in
    the thread; empty otherwise so a quiet day regenerates fresh."""
    previous = _live_conversation(user)
    if previous is None:
        return ""
    msgs = list(previous.messages.order_by("created_at"))
    discussion = msgs[2:]
    if not discussion:
        return ""

    lines = []
    for msg in discussion:
        if msg.role == "user":
            name = msg.user.full_name if msg.user else "User"
            lines.append(f"{name}: {msg.content}")
        else:
            lines.append(f"Assistant: {msg.content}")

    previous_plan = ""
    if len(msgs) > 1 and msgs[1].role == "assistant":
        previous_plan = msgs[1].content
    return PLAN_FEEDBACK_TEMPLATE.format(
        previous_plan=previous_plan, discussion="\n\n".join(lines)
    )


def generate_overnight_plan(user_id):
    """qcluster task: pre-generate one user's daily plan so the dash Plan
    button opens instantly. Generate first, then swap conversations: on
    failure the previous plan (or the on-open interactive fallback)
    survives. Discussion in the previous thread is folded in as guidance
    before the thread is replaced."""
    from django.db import transaction

    from apps.case.ai.gemini_client import send_to_gemini

    user = CustomUser.objects.filter(id=user_id, is_active=True).first()
    if user is None:
        logger.warning("Daily plan: user %s missing or inactive", user_id)
        return

    system_context = _agenda_system_prompt(user, thorough=True) + _plan_feedback(user)
    try:
        response_text, input_tokens, output_tokens = send_to_gemini(
            system_context=system_context,
            messages=[{"role": "user", "content": AUTO_START_MESSAGE}],
            model=AGENDA_MODEL,
        )
    except Exception:
        logger.exception(
            "Daily plan failed for %s; keeping previous plan", user.username
        )
        return

    if not response_text or not response_text.strip():
        logger.warning(
            "Daily plan: empty response for %s; keeping previous", user.username
        )
        return

    response_text = _apply_task_blocks(response_text.strip(), user)
    with transaction.atomic():
        Conversation.objects.filter(agenda_user=user).delete()
        conversation = Conversation.objects.create(
            agenda_user=user,
            title="Agenda",
            llm=AGENDA_MODEL,
            vet_citations=False,
        )
        Message.objects.create(
            conversation=conversation,
            role="user",
            content=AUTO_START_MESSAGE,
            user=user,
        )
        Message.objects.create(
            conversation=conversation,
            role="assistant",
            content=response_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


# ── Chat cycle ───────────────────────────────────────────────────────────────


def _live_conversation(user):
    return Conversation.objects.filter(agenda_user=user).first()


def _process_agenda_chat(conversation_id, user_id):
    """Background thread: the shared cache-status protocol, so the
    case:ai-status polling cycle works unchanged."""
    from apps.case.ai.gemini_client import send_to_gemini_streaming

    cache_key = f"ai_status_{conversation_id}"

    def is_cancelled():
        current = status_cache.get(cache_key)
        return bool(current) and current.get("status") == "cancelled"

    def update_status(status, message):
        if is_cancelled():
            return
        import time as _time

        current = status_cache.get(cache_key) or {}
        payload = {"status": status, "message": message}
        payload["started_at"] = current.get("started_at", _time.time())
        status_cache.set(cache_key, payload, timeout=RUNNING_TTL)

    heartbeat = RunHeartbeat(conversation_id).start()
    try:
        update_status("context", "Building context...")
        user = CustomUser.objects.get(id=user_id)
        conversation = Conversation.objects.get(id=conversation_id)
        system_context = _agenda_system_prompt(user)

        from apps.case.ai.context import build_chat_history

        chat_history = build_chat_history(conversation)

        update_status("connecting", "Connecting to AI...")

        def on_thought(thought):
            update_status("thinking", thought[:300])

        response_text, input_tokens, output_tokens = send_to_gemini_streaming(
            system_context,
            chat_history,
            model=AGENDA_MODEL,
            on_thought=on_thought,
            is_cancelled=is_cancelled,
            conversation_id=conversation.id,
        )

        if is_cancelled():
            return

        # Create any directed tasks and store the cleaned, confirmed text
        response_text = _apply_task_blocks(response_text, user)

        status_cache.set(
            cache_key,
            {
                "status": "complete",
                "message": "Complete",
                "response": response_text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "citations": [],
            },
            timeout=FINAL_TTL,
        )
    except InterruptedError:
        pass
    except Exception as exc:
        logger.exception("Agenda chat request failed")
        if not is_cancelled():
            status_cache.set(
                cache_key,
                {"status": "error", "message": str(exc)},
                timeout=FINAL_TTL,
            )
    finally:
        heartbeat.stop()


def _start_processing(conversation, user):
    status_cache.set(
        f"ai_status_{conversation.id}",
        {"status": "starting", "message": "Starting..."},
        timeout=RUNNING_TTL,
    )
    threading.Thread(
        target=_process_agenda_chat,
        args=(conversation.id, user.id),
        daemon=True,
    ).start()


@login_required
def agenda_window(request):
    """The standalone agenda window. With no live conversation, the daily
    agenda auto-generates: one click from dash to agenda."""
    conversation = _live_conversation(request.user)
    is_processing = False
    if conversation is None:
        conversation = Conversation.objects.create(
            agenda_user=request.user,
            title="Agenda",
            llm=AGENDA_MODEL,
            vet_citations=False,
        )
        Message.objects.create(
            conversation=conversation,
            role="user",
            content=AUTO_START_MESSAGE,
            user=request.user,
        )
        _start_processing(conversation, request.user)
        is_processing = True

    return render(
        request,
        "dash/agenda-window.html",
        {
            "conversation": conversation,
            "messages": conversation.messages.select_related("user").all(),
            "agenda": True,
            "is_processing": is_processing,
        },
    )


@login_required
@require_http_methods(["POST"])
def agenda_send(request):
    user_message = request.POST.get("message", "").strip()
    if not user_message:
        return HttpResponse(status=400)

    conversation = _live_conversation(request.user)
    if conversation is None:
        conversation = Conversation.objects.create(
            agenda_user=request.user,
            title="Agenda",
            llm=AGENDA_MODEL,
            vet_citations=False,
        )

    Message.objects.create(
        conversation=conversation,
        role="user",
        content=user_message,
        user=request.user,
    )
    _start_processing(conversation, request.user)

    return render(
        request,
        "case/ai/messages.html",
        {
            "messages": conversation.messages.all(),
            "conversation": conversation,
            "agenda": True,
            "is_processing": True,
        },
    )


@login_required
def agenda_messages(request):
    conversation = _live_conversation(request.user)
    messages = (
        conversation.messages.select_related("user").all() if conversation else []
    )
    return render(
        request,
        "case/ai/messages.html",
        {"messages": messages, "conversation": conversation, "agenda": True},
    )


@login_required
@require_http_methods(["POST"])
def agenda_discard(request):
    """Throw the conversation away; the next open starts fresh."""
    conversation = _live_conversation(request.user)
    if conversation is not None:
        conversation.delete()
    return render(request, "dash/agenda-closed.html")
