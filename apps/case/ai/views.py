"""
Views for AI chat within case analysis.
"""

import logging
import threading
import time

from django.contrib.auth.decorators import login_required
from django.db.models import F, Max
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import CustomUser
from apps.case.models import Fact, Highlight
from apps.case.views import get_matter_from_url, get_session_key, set_last_tab
from apps.management.selection import (
    all_visible_selected,
    clear_selected_ids,
    get_selected_ids,
    select_all_ids,
    selection_response,
    toggle_id,
)
from apps.matters.models import Matter
from apps.settings.models import Firm

from .context import (
    assemble_matter_context,
    build_request_info,
    load_legal_prompt,
)
from .filters import ConversationFilter
from .models import Conversation, Message
from .status import RUNNING_TTL, status_cache
from .tasks import process_ai_request

logger = logging.getLogger(__name__)

# Every llm key the dispatch understands: the picker's current choices plus
# the retired ones older conversations still carry ("claude" is Sonnet 4.6,
# "gemini-pro" is Gemini 2.5 Pro). Derived rather than spelled out, so adding
# a model to LLM_CHOICES doesn't have to be mirrored in each request handler.
RETIRED_LLMS = ("claude", "gemini-pro")
VALID_LLMS = {key for key, _ in Conversation.LLM_CHOICES} | set(RETIRED_LLMS)


def get_accessible_matters():
    """Get all matters accessible to logged-in users."""
    return Matter.objects.all()


def annotate_last_activity(queryset):
    """Annotate conversations with last message timestamp, falling back to created_at."""
    return queryset.select_related("draft_link").annotate(
        last_activity=Coalesce(Max("messages__created_at"), F("created_at"))
    )


def get_conversation_list_context(request, matter):
    """Filter/sort/selection context shared by the AI tab's list partials.

    The keyword/participant filter and the sort order persist per matter in
    the session ("ai_filter" key, applied through ConversationFilter);
    row selection rides its own session key.
    """
    filter_session_key = get_session_key("ai_filter", matter.id)
    filter_data = request.session.get(filter_session_key, {})

    conversations = annotate_last_activity(Conversation.objects.filter(matter=matter))
    if filter_data:
        conversations = ConversationFilter(filter_data, queryset=conversations).qs
    else:
        conversations = conversations.order_by("-created_at", "-id")

    current_order = filter_data.get("order_by", "-created_at")
    if isinstance(current_order, list):
        current_order = current_order[0] if current_order else "-created_at"

    conv_list = list(conversations)
    selection_key = get_session_key("selected_conversations", matter.id)
    selected_conversations = get_selected_ids(request, selection_key)
    visible_ids = [c.id for c in conv_list]

    participant_choices = list(
        CustomUser.objects.filter(ai_messages__conversation__matter=matter)
        .distinct()
        .order_by("first_name", "last_name")
    )
    participant_id = str(filter_data.get("participant", ""))
    selected_participant = next(
        (u for u in participant_choices if str(u.id) == participant_id), None
    )

    return {
        "matter": matter,
        "conversations": conv_list,
        "current_order": current_order,
        "selected_conversations": selected_conversations,
        "all_selected": all_visible_selected(selected_conversations, visible_ids),
        "filter_q": filter_data.get("q", ""),
        "participant_choices": participant_choices,
        "selected_participant": selected_participant,
    }


@login_required
def ai_index(request, matter_id):
    """Main AI view - list of conversations."""
    matter, matters = get_matter_from_url(request, matter_id)
    set_last_tab(request, matter_id, "ai")

    # Backfill: queue summary generation for documents missing summaries
    from apps.case.models import Document

    docs_needing_summary = Document.objects.filter(
        matter=matter,
        summary__isnull=True,
        ocr_text__isnull=False,
        ocr_status__in=["completed", "extracted"],
    )
    if docs_needing_summary.exists():
        from django_q.tasks import async_task

        for doc in docs_needing_summary[:20]:
            async_task(
                "apps.case.documents.tasks.generate_document_summary",
                doc.id,
                task_name=f"Summary-{doc.id}",
                group="summary_generation",
            )

    # Backfill: generate summaries for conversations missing them
    convos_needing_summary = Conversation.objects.filter(
        matter=matter,
        summary__isnull=True,
    ).exclude(messages=None)
    if convos_needing_summary.exists():
        import threading

        from .tasks import generate_conversation_summary

        for conv in convos_needing_summary[:20]:
            threading.Thread(
                target=generate_conversation_summary,
                args=(conv.id,),
                daemon=True,
            ).start()

    context = {
        "app": "matters",
        "subapp": "ai",
        "matters": matters,
        **get_conversation_list_context(request, matter),
    }

    return render(request, "case/ai/main.html", context)


@login_required
def ai_list(request, matter_id):
    """Return conversation list partial (for HTMX refresh)."""
    matter, _ = get_matter_from_url(request, matter_id)
    return render(
        request, "case/ai/list.html", get_conversation_list_context(request, matter)
    )


@login_required
def ai_sort(request, matter_id, order):
    """Sort conversations by a field."""
    filter_session_key = get_session_key("ai_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    current_order = filter_data.get("order_by", "")

    # Toggle sort direction if clicking the same column
    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    elif current_order == f"-{order}":
        new_order = order
    else:
        new_order = f"-{order}"  # Default to descending for new column

    filter_data["order_by"] = new_order
    request.session[filter_session_key] = filter_data

    return redirect("case:ai-list", matter_id=matter_id)


@login_required
def ai_filter(request, matter_id):
    """Update the conversation keyword/participant filter (session-persisted).

    The toolbar search input targets just the table (partial=table) so a
    swap mid-typing never steals focus; participant picks re-render the
    whole list so the dropdown's label updates too.
    """
    matter, _ = get_matter_from_url(request, matter_id)
    filter_session_key = get_session_key("ai_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    if "q" in request.GET:
        q = request.GET.get("q", "").strip()
        if q:
            filter_data["q"] = q
        else:
            filter_data.pop("q", None)
    if "participant" in request.GET:
        participant = request.GET.get("participant", "")
        if participant.isdigit():
            filter_data["participant"] = participant
        else:
            filter_data.pop("participant", None)
    request.session[filter_session_key] = filter_data

    template = (
        "case/ai/table.html"
        if request.GET.get("partial") == "table"
        else "case/ai/list.html"
    )
    return render(request, template, get_conversation_list_context(request, matter))


@login_required
def conversation_view(request, conv_id):
    """Standalone full-height view for a single conversation."""
    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter__in=get_accessible_matters()
    )
    matter = conversation.matter

    messages = conversation.messages.select_related("user").all()

    context = {
        "matter": matter,
        "conversation": conversation,
        "messages": messages,
    }

    return render(request, "case/ai/conversation-standalone.html", context)


@login_required
def new_conversation_view(request, matter_id):
    """Standalone view for a new (unsaved) conversation."""
    matter, _ = get_matter_from_url(request, matter_id)

    # Get LLM from query parameter
    llm = request.GET.get("llm", "gemini-pro-latest")
    if llm not in VALID_LLMS:
        llm = "gemini-pro-latest"

    provided_title = request.GET.get("title", "").strip()

    # Create a dummy conversation object for template (not saved). When the
    # user named the chat from the new-conversation prompt, use that name as
    # the display title; otherwise show the legacy "New Conversation" placeholder.
    conversation = Conversation(
        matter=matter,
        title=provided_title or "New Conversation",
        llm=llm,
    )

    context = {
        "matter": matter,
        "conversation": conversation,
        "messages": [],
        "is_new": True,
        "llm": llm,
        "provided_title": provided_title,
    }

    return render(request, "case/ai/conversation-standalone.html", context)


@login_required
def create_conversation(request, matter_id):
    """Materialize a new conversation before its first message.

    Normally the row is created lazily by send_message; actions that need a
    real conversation up front (linking a draft in a fresh chat window) POST
    here with the same fields the chat form carries and get the id back.
    """
    if request.method != "POST":
        return HttpResponse(status=405)
    matter, _ = get_matter_from_url(request, matter_id)
    llm = request.POST.get("llm", "gemini-pro-latest")
    if llm not in VALID_LLMS:
        llm = "gemini-pro-latest"
    conversation = Conversation.objects.create(
        matter=matter,
        title=request.POST.get("title", "").strip() or "New Conversation",
        llm=llm,
        user=request.user,
    )
    return JsonResponse({"id": conversation.id})


@login_required
def new_conversation_prompt(request, matter_id):
    """Return the modal that prompts the user to name a new conversation."""
    matter, _ = get_matter_from_url(request, matter_id)
    llm = request.GET.get("llm", "gemini-pro-latest")
    if llm not in VALID_LLMS:
        llm = "gemini-pro-latest"

    return render(
        request,
        "case/ai/new-conversation-modal.html",
        {
            "matter": matter,
            "llm": llm,
            "llm_choices": Conversation.LLM_CHOICES,
        },
    )


@login_required
def message_list(request, matter_id):
    """Return message list partial (for HTMX refresh)."""
    matter, _ = get_matter_from_url(request, matter_id)
    conversation_id = request.GET.get("conversation_id")

    try:
        conv_pk = int(conversation_id) if conversation_id else None
    except (TypeError, ValueError):
        conv_pk = None

    if conv_pk:
        conversation = get_object_or_404(
            Conversation, pk=conv_pk, matter__in=get_accessible_matters()
        )
    else:
        conversation = Conversation.objects.filter(matter=matter).first()

    messages = (
        conversation.messages.select_related("user").all() if conversation else []
    )

    return render(
        request,
        "case/ai/messages.html",
        {
            "messages": messages,
            "conversation": conversation,
            "matter": matter,
        },
    )


@login_required
def send_message(request, matter_id):
    """Handle user message submission and start background AI processing."""
    matter, _ = get_matter_from_url(request, matter_id)

    if request.method != "POST":
        return HttpResponse(status=405)

    user_message = request.POST.get("message", "").strip()
    conversation_id = request.POST.get("conversation_id")
    llm = request.POST.get("llm", "gemini-pro-latest")
    provided_title = request.POST.get("title", "").strip()

    if not user_message:
        return HttpResponse(status=400)

    # Validate llm
    if llm not in VALID_LLMS:
        llm = "gemini-pro-latest"

    # Get or create conversation
    is_new = False
    if conversation_id:
        conversation = get_object_or_404(
            Conversation, pk=conversation_id, matter__in=get_accessible_matters()
        )
    else:
        # Create conversation on first message. Prefer the title the user
        # entered in the new-conversation prompt; otherwise fall back to the
        # legacy first-50-chars-of-message behavior.
        if provided_title:
            title = provided_title
        else:
            title = user_message[:50]
            if len(user_message) > 50:
                title += "..."
        conversation = Conversation.objects.create(
            matter=matter,
            title=title,
            llm=llm,
            user=request.user,
        )
        is_new = True

    # Update title if this is first message and title is default
    if not is_new and conversation.title == "New Conversation":
        conversation.title = user_message[:50]
        if len(user_message) > 50:
            conversation.title += "..."
        conversation.save()

    # Save user message immediately with user attribution
    Message.objects.create(
        conversation=conversation, role="user", content=user_message, user=request.user
    )

    # Initialize status in cache
    cache_key = f"ai_status_{conversation.id}"
    status_cache.set(
        cache_key,
        {"status": "starting", "message": "Starting..."},
        timeout=RUNNING_TTL,
    )

    # Start background thread — context assembly + AI processing
    thread = threading.Thread(
        target=process_ai_request,
        args=(
            conversation.id,
            matter.id,
            user_message,
            request.user.id,
            conversation.llm,
        ),
        daemon=True,
    )
    thread.start()

    # Return messages with status indicator that will poll for updates
    response = render(
        request,
        "case/ai/messages.html",
        {
            "messages": conversation.messages.all(),
            "conversation": conversation,
            "matter": matter,
            "is_processing": True,
        },
    )

    # If new conversation, trigger update of hidden field and list refresh
    if is_new:
        response["HX-Trigger"] = "conversationCreated"
        response["X-Conversation-Id"] = str(conversation.id)

    return response


def _terminal(response):
    """Mark a status-poll response as the poller's last.

    status.html polls itself with hx-swap="morph" (idiomorph), and the
    protocol ends the every-1s interval by answering with a DIFFERENT
    root element, which morph replaces rather than patches. That only
    holds where idiomorph is loaded; without it htmx falls back to
    innerHTML, the reply lands INSIDE the indicator, and the interval
    runs on (2026-08-23: the intake chat window). HX-Reswap forces an
    outerHTML replacement of the poller whatever the page's swap
    support, so a terminal answer always takes the poller with it.
    """
    response["HX-Reswap"] = "outerHTML"
    return response


def _poll_ended():
    """Empty terminal response: an empty div under a DIFFERENT id than the
    poller, so a morph swap replaces the element (a same-id root would be
    patched in place, keeping its interval alive), plus HX-Reswap for
    pages without morph."""
    return _terminal(HttpResponse('<div id="ai-status-ended"></div>'))


@login_required
def ai_status(request, conv_id):
    """Return current AI processing status for polling."""
    # Plain pk lookup: conversations belong to a matter OR an intake, and
    # the old matter__in filter was Matter.objects.all() anyway
    conversation = get_object_or_404(Conversation, pk=conv_id)

    cache_key = f"ai_status_{conv_id}"
    status_data = status_cache.get(cache_key)
    if status_data is None:
        # send_message seeds this entry before spawning the worker thread,
        # and the thread's heartbeat keeps re-touching it while its
        # process is alive (see status.py). A missing entry while an
        # indicator is still polling therefore means the run died with
        # its process (deploy, reload, crash) and the entry expired. Say
        # so plainly instead of polling "Checking..." forever.
        #
        # But only when a reply is actually outstanding, i.e. the latest
        # message is the user's. A poll that lands after the reply (or
        # an earlier interruption note) was already written must not add
        # another: a poller that outlived its swap (2026-08-23, the intake
        # window lacked idiomorph, so "morph" fell back to innerHTML and
        # the indicator never went away) wrote one of these per second.
        latest = conversation.messages.order_by("-created_at").first()
        if latest is None or latest.role != "user":
            return _poll_ended()
        interrupted = Message.objects.create(
            conversation=conversation,
            role="assistant",
            content=(
                "This request was interrupted before it finished (the "
                "server restarted mid-run). Please re-send your message."
            ),
        )
        return _terminal(
            render(
                request,
                "case/ai/message-single.html",
                {"message": interrupted},
            )
        )

    if status_data["status"] == "complete":
        # Get verified citations from status data
        verified_citations = status_data.get("citations", [])
        logger.info(
            "Retrieved %d citations from cache for conversation %s",
            len(verified_citations),
            conv_id,
        )

        # Save assistant message with citations (research-kind payloads also
        # carry the research trail; classic payloads lack the key -> []).
        assistant_message = Message.objects.create(
            conversation=conversation,
            role="assistant",
            content=status_data["response"],
            input_tokens=status_data.get("input_tokens"),
            output_tokens=status_data.get("output_tokens"),
            verified_citations=verified_citations,
            research_trail=status_data.get("research_trail", []),
            activity_log=status_data.get("activity_log", []),
        )

        # Update conversation timestamp
        conversation.save()

        # Generate conversation summary in background thread. Intake chats
        # skip it: their summary happens once, at End & summarize.
        import threading

        from .tasks import generate_conversation_summary

        if conversation.matter_id:
            threading.Thread(
                target=generate_conversation_summary,
                args=(conversation.id,),
                daemon=True,
            ).start()

        # If the conversation has vetting enabled, seed pending vetting entries
        # on case citations and launch a background job to Flash-vet each one.
        if conversation.vet_citations:
            from .vetting import process_citation_vetting, seed_pending_vetting

            if seed_pending_vetting(assistant_message):
                threading.Thread(
                    target=process_citation_vetting,
                    args=(assistant_message.id,),
                    daemon=True,
                ).start()

        # Clear the cache
        status_cache.delete(cache_key)

        # Return just the new assistant message (replaces status indicator)
        return _terminal(
            render(
                request,
                "case/ai/message-single.html",
                {
                    "message": assistant_message,
                },
            )
        )

    if status_data["status"] == "error":
        # Save error as assistant message
        error_message = Message.objects.create(
            conversation=conversation,
            role="assistant",
            content=f"Error: Unable to get response. {status_data['message']}",
            activity_log=status_data.get("activity_log", []),
        )

        # Clear the cache
        status_cache.delete(cache_key)

        # Return just the error message (replaces status indicator)
        return _terminal(
            render(
                request,
                "case/ai/message-single.html",
                {
                    "message": error_message,
                },
            )
        )

    if status_data["status"] == "cancelled":
        # Keep cache entry (don't delete) so background thread's
        # is_cancelled() check continues to see "cancelled" status.
        return _poll_ended()

    # Calculate elapsed time if available
    elapsed_seconds = None
    if "started_at" in status_data:
        elapsed_seconds = int(time.time() - status_data["started_at"])

    # Still processing - return status indicator with continued polling
    return render(
        request,
        "case/ai/status.html",
        {
            "status": status_data["status"],
            "message": status_data["message"],
            "conversation": conversation,
            "elapsed_seconds": elapsed_seconds,
            # Both modes accumulate a live log: research logs its
            # searches/reads, classic logs context assembly + cite check.
            "activity_log": status_data.get("activity_log"),
        },
    )


@login_required
def cancel_request(request, conv_id):
    """Cancel an in-progress AI request."""
    # Plain pk lookup, same reasoning as ai_status: intake conversations
    # have no matter
    conversation = get_object_or_404(Conversation, pk=conv_id)

    if request.method != "POST":
        return HttpResponse(status=405)

    cache_key = f"ai_status_{conv_id}"
    status_data = status_cache.get(cache_key)

    if status_data and status_data.get("status") not in (
        "complete",
        "error",
        "cancelled",
    ):
        # Set cancelled status
        status_cache.set(
            cache_key,
            {
                "status": "cancelled",
                "message": "Request cancelled",
            },
            timeout=60,
        )

        # Delete the pending user message (last message if it's from user with no response)
        last_message = conversation.messages.order_by("-created_at").first()
        if last_message and last_message.role == "user":
            last_message.delete()

    # Return empty indicator (no polling) and trigger message list refresh
    return HttpResponse(
        '<div id="ai-status-indicator"></div>',
        headers={"HX-Trigger": "messagesUpdated"},
    )


@login_required
def delete_message(request, message_id):
    """Delete a message pair (user question + assistant response)."""
    message = get_object_or_404(
        Message, pk=message_id, conversation__matter__in=get_accessible_matters()
    )
    conversation = message.conversation

    if request.method != "POST":
        return HttpResponse(status=405)

    if message.role != "user":
        return HttpResponse("Can only delete user messages", status=403)

    # Delete the following assistant message if it exists
    next_message = (
        conversation.messages.filter(created_at__gt=message.created_at)
        .order_by("created_at")
        .first()
    )
    if next_message and next_message.role == "assistant":
        next_message.delete()
    message.delete()

    # Trigger messagesUpdated event to refresh the message list
    return HttpResponse(status=204, headers={"HX-Trigger": "messagesUpdated"})


@login_required
def conversation_list(request, matter_id):
    """Return conversation list partial."""
    matter, _ = get_matter_from_url(request, matter_id)

    conversations = Conversation.objects.filter(matter=matter)

    return render(
        request,
        "case/ai/conversation-list.html",
        {
            "conversations": conversations,
            "matter": matter,
        },
    )


@login_required
def select_conversation(request, conv_id):
    """Switch to a different conversation."""
    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter__in=get_accessible_matters()
    )
    matter = conversation.matter

    messages = conversation.messages.select_related("user").all()

    return render(
        request,
        "case/ai/chat-area.html",
        {
            "messages": messages,
            "conversation": conversation,
            "matter": matter,
        },
    )


@login_required
def delete_conversation(request, conv_id):
    """Delete a conversation."""
    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter__in=get_accessible_matters()
    )

    conversation.delete()

    # Trigger refresh of conversation list
    response = HttpResponse(status=204)
    response["HX-Trigger"] = "conversationsChanged"
    return response


@login_required
def clone_conversation(request, conv_id):
    """Clone a conversation with all its messages."""
    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter__in=get_accessible_matters()
    )

    # Create new conversation
    new_conversation = Conversation.objects.create(
        matter=conversation.matter,
        user=request.user,
        title=f"{conversation.title} (Copy)",
        llm=conversation.llm,
        kind=conversation.kind,
        effort=conversation.effort,
        vet_citations=conversation.vet_citations,
    )

    # Clone all messages
    for message in conversation.messages.all():
        Message.objects.create(
            conversation=new_conversation,
            role=message.role,
            content=message.content,
            user=message.user,
            input_tokens=message.input_tokens,
            output_tokens=message.output_tokens,
            verified_citations=message.verified_citations,
        )

    # Trigger refresh of conversation list
    response = HttpResponse(status=204)
    response["HX-Trigger"] = "conversationsChanged"
    return response


@login_required
def append_conversation_form(request, conv_id):
    """Show modal to select target conversation for append."""
    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter__in=get_accessible_matters()
    )

    # Get other conversations in the same matter
    other_conversations = (
        Conversation.objects.filter(matter=conversation.matter)
        .exclude(pk=conv_id)
        .order_by("-created_at")
    )

    return render(
        request,
        "case/ai/append-modal.html",
        {
            "conversation": conversation,
            "other_conversations": other_conversations,
        },
    )


@login_required
def append_conversation(request, conv_id):
    """Append messages from source conversation to target conversation."""
    source = get_object_or_404(
        Conversation, pk=conv_id, matter__in=get_accessible_matters()
    )

    if request.method != "POST":
        return HttpResponse(status=405)

    target_id = request.POST.get("target_id")
    if not target_id:
        return HttpResponse("No target conversation selected", status=400)

    target = get_object_or_404(Conversation, pk=target_id, matter=source.matter)

    # Append all messages from source to target
    for message in source.messages.all():
        Message.objects.create(
            conversation=target,
            role=message.role,
            content=message.content,
            user=message.user,
            input_tokens=message.input_tokens,
            output_tokens=message.output_tokens,
            verified_citations=message.verified_citations,
        )

    # Delete source conversation
    source.delete()

    # Trigger refresh of conversation list
    response = HttpResponse(status=204)
    response["HX-Trigger"] = "conversationsChanged"
    return response


@login_required
def split_conversation(request, message_id):
    """Split conversation from a message, moving it and subsequent messages to a new conversation."""
    message = get_object_or_404(
        Message, pk=message_id, conversation__matter__in=get_accessible_matters()
    )

    if request.method != "POST":
        return HttpResponse(status=405)

    if message.role != "user":
        return HttpResponse("Can only split from user messages", status=400)

    conversation = message.conversation

    # Get this message and all subsequent messages
    messages_to_move = conversation.messages.filter(
        created_at__gte=message.created_at
    ).order_by("created_at")

    # Create new conversation
    new_conversation = Conversation.objects.create(
        matter=conversation.matter,
        user=request.user,
        title=f"{conversation.title} (Split)",
        llm=conversation.llm,
        kind=conversation.kind,
        effort=conversation.effort,
        vet_citations=conversation.vet_citations,
    )

    # Move messages to new conversation
    for msg in messages_to_move:
        Message.objects.create(
            conversation=new_conversation,
            role=msg.role,
            content=msg.content,
            user=msg.user,
            input_tokens=msg.input_tokens,
            output_tokens=msg.output_tokens,
            verified_citations=msg.verified_citations,
        )
        msg.delete()

    # Trigger refresh
    response = HttpResponse(status=204)
    response["HX-Trigger"] = "messagesUpdated, conversationsChanged"
    return response


@login_required
def set_ai_context(request, conv_id, state):
    """Set the ai_context state on a conversation."""
    if state not in ("auto", "always", "never"):
        return HttpResponse(status=400)

    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter__in=get_accessible_matters()
    )

    conversation.ai_context = state
    conversation.save()

    return render(
        request,
        "case/ai/ai-context-cell.html",
        {"conv": conversation},
    )


@login_required
@require_POST
def set_vet_citations(request, conv_id, state):
    """Toggle the vet_citations flag on a conversation (on/off)."""
    if state not in ("on", "off"):
        return HttpResponse(status=400)

    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter__in=get_accessible_matters()
    )

    conversation.vet_citations = state == "on"
    conversation.save(update_fields=["vet_citations"])

    return render(
        request,
        "case/ai/vet-citations-pill.html",
        {"conversation": conversation},
    )


@login_required
def citation_vetting_detail(request, message_id, citation_index):
    """Return a modal fragment describing the Flash vetting verdict for one citation."""
    message = get_object_or_404(
        Message,
        pk=message_id,
        conversation__matter__in=get_accessible_matters(),
    )

    citations = message.verified_citations or []
    if citation_index < 0 or citation_index >= len(citations):
        return HttpResponse(status=404)

    citation = citations[citation_index]
    return render(
        request,
        "case/ai/citation-vetting-modal.html",
        {
            "citation": citation,
            "vetting": citation.get("vetting") or {},
            "message": message,
        },
    )


@login_required
def message_vetting_status(request, message_id):
    """Return the updated assistant message content with current vetting badges.

    The wrapping element advertises an HTMX poll trigger only while any case
    citation is still in a non-terminal vetting state; once everything is
    done, the fragment is returned without the trigger and polling stops.
    """
    message = get_object_or_404(
        Message,
        pk=message_id,
        conversation__matter__in=get_accessible_matters(),
    )

    return render(
        request,
        "case/ai/vetting-wrapper.html",
        {"message": message},
    )


@login_required
def rename_conversation(request, conv_id):
    """Rename a conversation - POST saves and closes modal."""
    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter__in=get_accessible_matters()
    )

    if request.method == "POST":
        new_title = request.POST.get("title", "").strip()
        if new_title:
            conversation.title = new_title[:255]
            conversation.save()

        # Check if request came from standalone view
        if request.headers.get("HX-Target") == "conversationTitle":
            # From standalone view - return title partial
            return render(
                request,
                "case/ai/conversation-title.html",
                {
                    "conversation": conversation,
                },
            )

        # From modal - return 204 to close modal and trigger list refresh
        return HttpResponse(status=204, headers={"HX-Trigger": "conversationsChanged"})

    # GET - return edit form for standalone view
    return render(
        request,
        "case/ai/conversation-rename-inline.html",
        {
            "conversation": conversation,
        },
    )


@login_required
def rename_form(request, conv_id):
    """Return rename modal for conversation."""
    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter__in=get_accessible_matters()
    )

    return render(
        request,
        "case/ai/rename-modal.html",
        {
            "conversation": conversation,
            "matter": conversation.matter,
        },
    )


@login_required
def prompt_editor_modal(request, matter_id):
    """Return the rich text prompt editor modal."""
    matter, _ = get_matter_from_url(request, matter_id)
    conversation_id = request.GET.get("conversation_id", "")
    llm = request.GET.get("llm", "gemini-pro-latest")
    title = request.GET.get("title", "")

    return render(
        request,
        "case/ai/prompt-editor-modal.html",
        {
            "matter": matter,
            "conversation_id": conversation_id,
            "llm": llm,
            "title": title,
        },
    )


@login_required
def create_prompt(request, matter_id):
    """Generate a prompt stuffing document for external AI chat clients."""
    matter, _ = get_matter_from_url(request, matter_id)

    # Load ai-prompt.md content with jurisdiction substitution
    company = Firm.objects.first()
    jurisdiction = (
        matter.jurisdiction
        or (company.jurisdiction if company else "")
        or "United States common law"
    )
    legal_guidelines = load_legal_prompt(jurisdiction=jurisdiction)

    # Build case timeline from facts
    facts = Fact.objects.filter(matter=matter).order_by("date", "id")
    timeline_lines = []
    for fact in facts:
        if fact.date:
            line = f"- {fact.date}: {fact.description}"
        else:
            line = f"- (No date): {fact.description}"

        # Add source citations if available
        sources = []
        for doc in fact.documents.all()[:2]:
            if doc.citation:
                sources.append(doc.citation)
        for hl in fact.highlights.all()[:2]:
            if hl.citation:
                sources.append(hl.citation)
        if sources:
            line += f" {', '.join(sources)}"

        timeline_lines.append(line)

    timeline_section = ""
    if timeline_lines:
        timeline_section = "\n\n## Case Timeline\n\n" + "\n".join(timeline_lines)

    # Build highlights section
    highlights = (
        Highlight.objects.filter(document__matter=matter)
        .select_related("document")
        .order_by("-importance", "document__name", "page_number")
    )
    highlight_lines = []
    for hl in highlights:
        # Format: slug/title, then the text, then citation
        line = f"### {hl.slug}\n\n> {hl.text}\n\n{hl.citation}"
        highlight_lines.append(line)

    highlights_section = ""
    if highlight_lines:
        highlights_section = (
            "\n\n## Key Highlights\n\n"
            "The following are key highlights from the case documents "
            "as identified by an attorney:\n\n" + "\n\n".join(highlight_lines)
        )

    # Build the prompt text with proper markdown formatting. The header
    # (request date, requesting party, firm team roster) is the same block
    # the chat system prompt uses — one source of truth for who's who.
    prompt_text = f"""{build_request_info(request.user)}
## General Guidelines for Responding

{legal_guidelines}{timeline_section}{highlights_section}"""

    context = {
        "matter": matter,
        "prompt_text": prompt_text,
    }

    return render(request, "case/ai/prompt.html", context)


def _importance_label(importance):
    """Map importance value (1-5) to a display label."""
    if importance >= 4:
        return "high"
    elif importance >= 3:
        return "med"
    else:
        return "low"


@login_required
def context_preview(request, matter_id):
    """Preview the AI context prompt for a matter."""
    from collections import OrderedDict

    from apps.case.models import CaseLaw, Document

    from .context import (
        collect_context_items,
        format_contacts,
        format_events,
        format_matter_overview,
        format_proceedings,
        format_settlement,
        format_tasks,
        load_legal_prompt,
    )
    from .selector import _resolve_content, build_manifest, estimate_tokens

    matter, _ = get_matter_from_url(request, matter_id)

    # Resolve jurisdiction
    company = Firm.objects.first()
    jurisdiction = (
        matter.jurisdiction
        or (company.jurisdiction if company else "")
        or "United States common law"
    )

    # --- Fixed context sections (always included) ---
    sections = []

    legal_prompt = load_legal_prompt(jurisdiction=jurisdiction)
    sections.append(
        {"title": "Legal Guidelines", "content": legal_prompt, "expanded": False}
    )

    sections.append(
        {
            "title": "Matter Overview",
            "content": format_matter_overview(matter),
            "expanded": True,
        }
    )

    sections.append({"title": "Contacts & Parties", "content": format_contacts(matter)})

    sections.append(
        {"title": "Court Proceedings", "content": format_proceedings(matter)}
    )

    sections.append({"title": "Tasks", "content": format_tasks(matter)})
    sections.append({"title": "Events", "content": format_events(matter)})
    sections.append(
        {"title": "Settlement Information", "content": format_settlement(matter)}
    )

    # --- Always-included items grouped by type ---
    all_items = collect_context_items(matter)

    # Add timeline/facts as a flat section in case details
    fact_items = [item for item in all_items if item.item_type == "fact"]
    if fact_items:
        fact_lines = [item.content.replace("**", "").strip() for item in fact_items]
        sections.append(
            {
                "title": f"Timeline ({len(fact_items)} facts)",
                "content": "\n\n".join(fact_lines),
            }
        )

    # Define display order and labels for item types (facts handled above)
    type_config = OrderedDict(
        [
            ("document", "Documents"),
            ("caselaw", "Case Law"),
            ("highlight", "Highlights"),
            ("note", "Notes"),
            ("library", "Library Notes"),
            ("conversation", "Reference Conversations"),
        ]
    )

    # Group items by type
    type_groups = []
    for type_key, title in type_config.items():
        items = [item for item in all_items if item.item_type == type_key]
        if items:
            type_groups.append(
                {
                    "title": title,
                    "count": len(items),
                    "items": [
                        {
                            "name": item.content.split("\n")[0]
                            .replace("**", "")
                            .strip(),
                            "content": item.content,
                            "importance": item.importance,
                            "importance_label": _importance_label(item.importance),
                        }
                        for item in items
                    ],
                }
            )

    # --- Auto selection pool ---
    manifest_items, content_map = build_manifest(matter)

    # --- Excluded items (ai_context="never") ---
    excluded_items = []
    for doc in Document.objects.filter(matter=matter, ai_context="never"):
        excluded_items.append(
            {
                "type": "Document",
                "name": doc.name,
                "category": doc.category,
                "date": doc.date,
            }
        )
    for cl in CaseLaw.objects.filter(matter=matter, ai_context="never"):
        excluded_items.append(
            {
                "type": "Case Law",
                "name": cl.case_name,
                "category": cl.court or "",
                "date": cl.date_filed,
            }
        )

    # --- Token stats ---
    baseline_text = assemble_matter_context(matter, user=request.user)
    baseline_tokens = estimate_tokens(baseline_text)

    auto_pool_tokens = sum(
        estimate_tokens(_resolve_content((item.item_type, item.item_id), content_map))
        for item in manifest_items
        if (item.item_type, item.item_id) in content_map
    )

    total_tokens = baseline_tokens + auto_pool_tokens

    # --- Cost estimates per model ---
    # One row per picker choice (LLM_CHOICES), input price per 1M tokens.
    model_costs = [
        {"name": "Gemini 2.5 Flash", "input_price": 0.15, "context_limit": 1_000_000},
        {
            "name": "Gemini Pro (Latest)",
            "input_price": 2.00,
            "context_limit": 1_000_000,
        },
        {"name": "Claude Sonnet 4.6", "input_price": 3.00, "context_limit": 1_000_000},
        {"name": "Claude Opus 4.8", "input_price": 5.00, "context_limit": 1_000_000},
        {"name": "Claude Opus 4.6", "input_price": 5.00, "context_limit": 1_000_000},
    ]

    for model in model_costs:
        model["baseline_cost"] = (baseline_tokens / 1_000_000) * model["input_price"]
        model["max_cost"] = (total_tokens / 1_000_000) * model["input_price"]
        model["baseline_usage_pct"] = (baseline_tokens / model["context_limit"]) * 100
        model["max_usage_pct"] = (total_tokens / model["context_limit"]) * 100
        model["exceeded"] = total_tokens > model["context_limit"]
        model["warning"] = (
            total_tokens > model["context_limit"] * 0.8 and not model["exceeded"]
        )

    return render(
        request,
        "case/ai/context-preview.html",
        {
            "matter": matter,
            "sections": sections,
            "type_groups": type_groups,
            "baseline_tokens": baseline_tokens,
            "auto_pool_tokens": auto_pool_tokens,
            "total_tokens": total_tokens,
            "manifest_items": manifest_items,
            "manifest_count": len(manifest_items),
            "excluded_items": excluded_items,
            "excluded_count": len(excluded_items),
            "model_costs": model_costs,
        },
    )


# --------------------------------------------------------------------------
# Conversation Selection & Bulk Actions
# --------------------------------------------------------------------------

CONVERSATIONS_TRIGGER = "conversationsChanged"


@login_required
@require_POST
def ai_toggle_select(request, matter_id, conv_id):
    get_object_or_404(Conversation, pk=conv_id)
    session_key = get_session_key("selected_conversations", matter_id)
    toggle_id(request, session_key, conv_id)
    return selection_response(CONVERSATIONS_TRIGGER)


@login_required
@require_POST
def ai_select_all(request, matter_id):
    matter, _ = get_matter_from_url(request, matter_id)
    conversations = Conversation.objects.filter(matter=matter)
    visible_ids = [c.id for c in conversations]
    session_key = get_session_key("selected_conversations", matter_id)
    select_all_ids(request, session_key, visible_ids)
    return selection_response(CONVERSATIONS_TRIGGER)


@login_required
@require_POST
def ai_clear_selection(request, matter_id):
    session_key = get_session_key("selected_conversations", matter_id)
    clear_selected_ids(request, session_key)
    return selection_response(CONVERSATIONS_TRIGGER)


@login_required
@require_POST
def ai_bulk_set_context(request, matter_id, state):
    """Bulk set ai_context on selected conversations."""
    if state not in ("auto", "always", "never"):
        return HttpResponse(status=400)

    session_key = get_session_key("selected_conversations", matter_id)
    selected = get_selected_ids(request, session_key)
    if not selected:
        return HttpResponse(status=400)

    Conversation.objects.filter(id__in=selected).update(ai_context=state)
    clear_selected_ids(request, session_key)
    return selection_response(CONVERSATIONS_TRIGGER)


@login_required
@require_POST
def ai_bulk_delete(request, matter_id):
    """Bulk delete selected conversations."""
    session_key = get_session_key("selected_conversations", matter_id)
    selected = get_selected_ids(request, session_key)
    if not selected:
        return HttpResponse(status=400)

    Conversation.objects.filter(id__in=selected).delete()
    clear_selected_ids(request, session_key)
    return selection_response(CONVERSATIONS_TRIGGER)
