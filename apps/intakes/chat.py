"""Intake AI chat: converse with the AI about a prospective-client intake.

Reuses the case-chat machinery (Conversation/Message models, the cache
status protocol polled by case:ai-status, the shared message templates)
with intake context instead of matter context, pinned to Gemini Pro. At
most one live conversation per intake - resumable until explicitly ended.
"End & summarize" posts a Kosmos comment with the conclusions and deletes
the conversation; "Discard" just deletes it.
"""

import logging
import threading

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.case.ai.models import Conversation, Message
from apps.intakes.assess import _intake_context
from apps.intakes.inbound import _kosmos_user
from apps.intakes.models import Intake, Note

logger = logging.getLogger(__name__)

# Fixed model for intake chats (no picker); an existing dispatch key.
INTAKE_CHAT_MODEL = "gemini-pro-latest"

CHAT_PREAMBLE = """You are discussing a prospective-client INTAKE with the firm - a potential
case that has not been accepted yet. Help the attorney think it through:
answer questions about the facts, evaluate theories, weigh whether the
engagement is worth taking, and suggest what to ask or collect next. The
intake's details, its notes chronology, and the current AI assessment
follow below. Be frank and concise."""

SUMMARY_PROMPT = """You summarize an AI chat about a prospective-client intake for the firm's
notes log. Summarize the CONCLUSIONS reached in the course of the
conversation - positions taken, theories accepted or rejected, decisions
and next steps - not a play-by-play of the exchange. Markdown, under 500
words; considerably shorter is better when the conversation was short.
Return only the summary text."""

CHAT_TEXT_LIMIT = 100_000


def _system_prompt(intake, user):
    from apps.case.ai.context import build_request_info, load_legal_prompt
    from apps.settings.models import Firm

    company = Firm.objects.first()
    jurisdiction = (company.jurisdiction if company else "") or (
        "United States common law"
    )
    parts = [
        build_request_info(user),
        load_legal_prompt(jurisdiction),
        "\n---\n",
        CHAT_PREAMBLE,
        "",
        _intake_context(intake),
    ]
    if intake.assessment:
        parts += ["", "INTAKE ASSESSMENT (current AI read)", intake.assessment]
    return "\n".join(parts)


def _live_conversation(intake):
    return Conversation.objects.filter(intake=intake).first()


def _process_intake_chat(conversation_id, intake_id, user_id):
    """Background thread: same cache-status protocol process_ai_request
    uses, so the shared case:ai-status polling cycle works unchanged."""
    from django.contrib.auth import get_user_model

    from apps.case.ai.gemini_client import send_to_gemini_streaming

    cache_key = f"ai_status_{conversation_id}"

    def is_cancelled():
        current = cache.get(cache_key)
        return bool(current) and current.get("status") == "cancelled"

    def update_status(status, message):
        if is_cancelled():
            return
        import time as _time

        current = cache.get(cache_key) or {}
        payload = {"status": status, "message": message}
        if "started_at" in current:
            payload["started_at"] = current["started_at"]
        else:
            payload["started_at"] = _time.time()
        cache.set(cache_key, payload, timeout=600)

    try:
        update_status("context", "Building context...")
        intake = Intake.objects.get(id=intake_id)
        user = get_user_model().objects.get(id=user_id)
        conversation = Conversation.objects.get(id=conversation_id)
        system_context = _system_prompt(intake, user)

        chat_history = [
            {"role": msg.role, "content": msg.content}
            for msg in conversation.messages.all()
        ]

        update_status("connecting", "Connecting to AI...")

        def on_thought(thought):
            update_status("thinking", thought[:300])

        response_text, input_tokens, output_tokens = send_to_gemini_streaming(
            system_context,
            chat_history,
            model=INTAKE_CHAT_MODEL,
            on_thought=on_thought,
            is_cancelled=is_cancelled,
            conversation_id=conversation.id,
        )

        if is_cancelled():
            return

        cache.set(
            cache_key,
            {
                "status": "complete",
                "message": "Complete",
                "response": response_text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "citations": [],
            },
            timeout=600,
        )
    except InterruptedError:
        pass
    except Exception as exc:
        logger.exception("Intake chat request failed")
        if not is_cancelled():
            cache.set(
                cache_key,
                {"status": "error", "message": str(exc)},
                timeout=600,
            )


@login_required
def chat_window(request, id):
    """The standalone chat window: resumes the intake's one live
    conversation, or offers a fresh unsaved one."""
    intake = get_object_or_404(Intake, pk=id)
    conversation = _live_conversation(intake)
    is_new = conversation is None
    if is_new:
        conversation = Conversation(
            intake=intake, llm=INTAKE_CHAT_MODEL, vet_citations=False
        )
        messages = []
    else:
        messages = conversation.messages.select_related("user").all()
    return render(
        request,
        "intakes/chat-window.html",
        {
            "intake": intake,
            "conversation": conversation,
            "messages": messages,
            "is_new": is_new,
        },
    )


@login_required
@require_http_methods(["POST"])
def chat_send(request, id):
    """Mirror of the case send_message cycle, intake-scoped."""
    intake = get_object_or_404(Intake, pk=id)
    user_message = request.POST.get("message", "").strip()
    if not user_message:
        return HttpResponse(status=400)

    conversation = _live_conversation(intake)
    is_new = conversation is None
    if is_new:
        title = user_message[:50] + ("..." if len(user_message) > 50 else "")
        conversation = Conversation.objects.create(
            intake=intake,
            title=title,
            llm=INTAKE_CHAT_MODEL,
            vet_citations=False,
        )

    Message.objects.create(
        conversation=conversation,
        role="user",
        content=user_message,
        user=request.user,
    )

    cache.set(
        f"ai_status_{conversation.id}",
        {"status": "starting", "message": "Starting..."},
        timeout=600,
    )
    threading.Thread(
        target=_process_intake_chat,
        args=(conversation.id, intake.id, request.user.id),
        daemon=True,
    ).start()

    response = render(
        request,
        "case/ai/messages.html",
        {
            "messages": conversation.messages.all(),
            "conversation": conversation,
            "intake": intake,
            "is_processing": True,
        },
    )
    if is_new:
        response["X-Conversation-Id"] = str(conversation.id)
    return response


@login_required
def chat_messages(request, id):
    """Refresh target for the messagesUpdated trigger."""
    intake = get_object_or_404(Intake, pk=id)
    conversation = _live_conversation(intake)
    messages = (
        conversation.messages.select_related("user").all() if conversation else []
    )
    return render(
        request,
        "case/ai/messages.html",
        {"messages": messages, "conversation": conversation, "intake": intake},
    )


def _transcript(conversation):
    lines = []
    for msg in conversation.messages.select_related("user"):
        if msg.role == "user":
            name = (
                (msg.user.get_full_name() or msg.user.username) if msg.user else "User"
            )
            lines.append(f"[User - {name}]: {msg.content}")
        else:
            lines.append(f"[Assistant]: {msg.content}")
    return "\n\n".join(lines)[:CHAT_TEXT_LIMIT]


@login_required
@require_http_methods(["POST"])
def chat_end(request, id):
    """End & summarize: post the conclusions as a Kosmos comment, then
    delete the conversation. On summary failure the conversation is kept
    so nothing is lost."""
    from apps.case.ai.gemini_client import send_to_gemini

    intake = get_object_or_404(Intake, pk=id)
    conversation = _live_conversation(intake)
    if conversation is None:
        return render(request, "intakes/chat-closed.html", {"intake": intake})

    try:
        summary, _, _ = send_to_gemini(
            SUMMARY_PROMPT,
            [{"role": "user", "content": _transcript(conversation)}],
            model="gemini-2.5-flash",
        )
        summary = summary.strip()
        if not summary:
            raise ValueError("AI returned an empty summary")
    except Exception as exc:
        logger.exception("Intake chat summary failed")
        return render(
            request,
            "intakes/chat-window.html",
            {
                "intake": intake,
                "conversation": conversation,
                "messages": conversation.messages.select_related("user").all(),
                "is_new": False,
                "end_error": str(exc),
            },
        )

    now = timezone.localtime()
    Note.objects.create(
        intake=intake,
        user=_kosmos_user(),
        date=now.date(),
        time=now.time(),
        type="Comment",
        details=f"**AI chat summary:** {summary}",
    )
    conversation.delete()
    return render(request, "intakes/chat-closed.html", {"intake": intake})


@login_required
@require_http_methods(["POST"])
def chat_discard(request, id):
    """Throw the conversation away without a note."""
    intake = get_object_or_404(Intake, pk=id)
    conversation = _live_conversation(intake)
    if conversation is not None:
        conversation.delete()
    return render(request, "intakes/chat-closed.html", {"intake": intake})
