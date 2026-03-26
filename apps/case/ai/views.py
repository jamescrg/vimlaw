"""
Views for AI chat within case analysis.
"""

import logging
import threading
import time
from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import F, Max
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.case.models import Fact, Highlight
from apps.case.views import get_matter_from_url, get_session_key, set_last_tab
from apps.matters.models import Matter
from apps.settings.models import Company

from .context import (
    assemble_matter_context,
    load_legal_prompt,
)
from .filters import ConversationFilter
from .models import ChatAttachment, Conversation, Message
from .tasks import process_ai_request, process_chat_attachment_ocr

logger = logging.getLogger(__name__)


def get_accessible_matters():
    """Get all matters accessible to logged-in users (currently all open matters)."""
    return Matter.objects.filter(status="Open")


def get_selected_llm(request):
    """Get the selected LLM from session, defaulting to gemini-pro-latest."""
    return request.session.get("ai_selected_llm", "gemini-pro-latest")


def get_llm_display(llm_key):
    """Get the display name for an LLM key."""
    llm_dict = dict(Conversation.LLM_CHOICES)
    return llm_dict.get(llm_key, llm_key)


def annotate_last_activity(queryset):
    """Annotate conversations with last message timestamp, falling back to created_at."""
    return queryset.annotate(
        last_activity=Coalesce(Max("messages__created_at"), F("created_at"))
    )


@login_required
def ai_index(request, matter_id):
    """Main AI view - list of conversations."""
    matter, matters = get_matter_from_url(request, matter_id)
    set_last_tab(request, matter_id, "ai")

    # Get filter data from session
    filter_session_key = get_session_key("ai_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    # Get conversations and apply filter with last_activity annotation
    conversations = annotate_last_activity(Conversation.objects.filter(matter=matter))
    if filter_data:
        filter_obj = ConversationFilter(filter_data, queryset=conversations)
        conversations = filter_obj.qs
    else:
        conversations = conversations.order_by("-created_at", "-id")

    # Get current sort order
    current_order = filter_data.get("order_by", "-created_at")
    if isinstance(current_order, list):
        current_order = current_order[0] if current_order else "-created_at"

    # Get selected LLM from session
    selected_llm = get_selected_llm(request)

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

    # Backfill: queue summary generation for conversations missing summaries
    convos_needing_summary = Conversation.objects.filter(
        matter=matter,
        summary__isnull=True,
    ).exclude(messages=None)
    if convos_needing_summary.exists():
        from django_q.tasks import async_task as async_task_conv

        for conv in convos_needing_summary[:20]:
            async_task_conv(
                "apps.case.ai.tasks.generate_conversation_summary",
                conv.id,
                task_name=f"ConvSummary-{conv.id}",
                group="conversation_summary",
            )

    context = {
        "app": "matters",
        "subapp": "ai",
        "matter": matter,
        "matters": matters,
        "conversations": conversations,
        "current_order": current_order,
        "selected_llm": selected_llm,
        "selected_llm_display": get_llm_display(selected_llm),
        "llm_choices": Conversation.LLM_CHOICES,
    }

    return render(request, "case/ai/main.html", context)


@login_required
def ai_list(request, matter_id):
    """Return conversation list partial (for HTMX refresh)."""
    matter, _ = get_matter_from_url(request, matter_id)

    # Get filter data from session
    filter_session_key = get_session_key("ai_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    # Get conversations and apply filter with last_activity annotation
    conversations = annotate_last_activity(Conversation.objects.filter(matter=matter))
    if filter_data:
        filter_obj = ConversationFilter(filter_data, queryset=conversations)
        conversations = filter_obj.qs
    else:
        conversations = conversations.order_by("-created_at", "-id")

    # Get current sort order
    current_order = filter_data.get("order_by", "-created_at")
    if isinstance(current_order, list):
        current_order = current_order[0] if current_order else "-created_at"

    # Get selected LLM from session
    selected_llm = get_selected_llm(request)

    return render(
        request,
        "case/ai/list.html",
        {
            "conversations": conversations,
            "matter": matter,
            "current_order": current_order,
            "selected_llm": selected_llm,
            "selected_llm_display": get_llm_display(selected_llm),
            "llm_choices": Conversation.LLM_CHOICES,
        },
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
def ai_select_llm(request, matter_id, llm):
    """Set the selected LLM in session."""
    valid_llms = [choice[0] for choice in Conversation.LLM_CHOICES]
    if llm in valid_llms:
        request.session["ai_selected_llm"] = llm
    return redirect("case:ai-list", matter_id=matter_id)


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
    if llm not in [
        "claude",
        "claude-opus",
        "gemini-flash",
        "gemini-pro",
        "gemini-pro-latest",
    ]:
        llm = "gemini-pro-latest"

    # Create a dummy conversation object for template (not saved)
    conversation = Conversation(
        matter=matter,
        title="New Conversation",
        llm=llm,
    )

    context = {
        "matter": matter,
        "conversation": conversation,
        "messages": [],
        "is_new": True,
        "llm": llm,
    }

    return render(request, "case/ai/conversation-standalone.html", context)


@login_required
def message_list(request, matter_id):
    """Return message list partial (for HTMX refresh)."""
    matter, _ = get_matter_from_url(request, matter_id)
    conversation_id = request.GET.get("conversation_id")

    if conversation_id:
        conversation = get_object_or_404(
            Conversation, pk=conversation_id, matter__in=get_accessible_matters()
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

    if not user_message:
        return HttpResponse(status=400)

    # Validate llm
    if llm not in [
        "claude",
        "claude-opus",
        "gemini-flash",
        "gemini-pro",
        "gemini-pro-latest",
    ]:
        llm = "gemini-pro-latest"

    # Get or create conversation
    is_new = False
    if conversation_id:
        conversation = get_object_or_404(
            Conversation, pk=conversation_id, matter__in=get_accessible_matters()
        )
    else:
        # Create conversation on first message
        title = user_message[:50]
        if len(user_message) > 50:
            title += "..."
        conversation = Conversation.objects.create(matter=matter, title=title, llm=llm)
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
    cache.set(
        cache_key,
        {"status": "starting", "message": "Starting..."},
        timeout=600,
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


@login_required
def ai_status(request, conv_id):
    """Return current AI processing status for polling."""
    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter__in=get_accessible_matters()
    )

    cache_key = f"ai_status_{conv_id}"
    status_data = cache.get(cache_key, {"status": "unknown", "message": "Checking..."})

    if status_data["status"] == "complete":
        # Get verified citations from status data
        verified_citations = status_data.get("citations", [])
        logger.info(
            "Retrieved %d citations from cache for conversation %s",
            len(verified_citations),
            conv_id,
        )

        # Save assistant message with citations
        assistant_message = Message.objects.create(
            conversation=conversation,
            role="assistant",
            content=status_data["response"],
            input_tokens=status_data.get("input_tokens"),
            output_tokens=status_data.get("output_tokens"),
            verified_citations=verified_citations,
        )

        # Update conversation timestamp
        conversation.save()

        # Generate conversation summary async
        try:
            from django_q.tasks import async_task

            async_task(
                "apps.case.ai.tasks.generate_conversation_summary",
                conversation.id,
                task_name=f"ConvSummary-{conversation.id}",
                group="conversation_summary",
            )
        except Exception:
            logger.warning("Failed to queue conversation summary task")

        # Clear the cache
        cache.delete(cache_key)

        # Return just the new assistant message (replaces status indicator)
        return render(
            request,
            "case/ai/message-single.html",
            {
                "message": assistant_message,
            },
        )

    if status_data["status"] == "error":
        # Save error as assistant message
        error_message = Message.objects.create(
            conversation=conversation,
            role="assistant",
            content=f"Error: Unable to get response. {status_data['message']}",
        )

        # Clear the cache
        cache.delete(cache_key)

        # Return just the error message (replaces status indicator)
        return render(
            request,
            "case/ai/message-single.html",
            {
                "message": error_message,
            },
        )

    if status_data["status"] == "cancelled":
        # Return empty div to remove the status indicator.
        # Keep cache entry (don't delete) so background thread's
        # is_cancelled() check continues to see "cancelled" status.
        return HttpResponse('<div id="ai-status-indicator"></div>')

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
        },
    )


@login_required
def cancel_request(request, conv_id):
    """Cancel an in-progress AI request."""
    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter__in=get_accessible_matters()
    )

    if request.method != "POST":
        return HttpResponse(status=405)

    cache_key = f"ai_status_{conv_id}"
    status_data = cache.get(cache_key)

    if status_data and status_data.get("status") not in (
        "complete",
        "error",
        "cancelled",
    ):
        # Set cancelled status
        cache.set(
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

    return render(
        request,
        "case/ai/prompt-editor-modal.html",
        {
            "matter": matter,
            "conversation_id": conversation_id,
            "llm": llm,
        },
    )


@login_required
def create_prompt(request, matter_id):
    """Generate a prompt stuffing document for external AI chat clients."""
    matter, _ = get_matter_from_url(request, matter_id)

    # Load ai-prompt.md content with jurisdiction substitution
    company = Company.objects.first()
    jurisdiction = (
        matter.jurisdiction
        or (company.jurisdiction if company else "")
        or "United States common law"
    )
    legal_guidelines = load_legal_prompt(jurisdiction=jurisdiction)

    # Determine user role description
    user = request.user
    if user.is_attorney:
        role_description = f"{user.get_full_name()} is an attorney"
    else:
        role_description = (
            f"{user.get_full_name()} is a paralegal supporting an attorney"
        )

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

    # Build the prompt text with proper markdown formatting

    company = Company.objects.first()

    company_name = company.name if company else ""
    prompt_text = f"""## Request Date

{date.today().strftime("%B %d, %Y")}

## Requesting Party

- Name: {user.get_full_name()}
- Email: {user.email}
- Role: {role_description}
- Law Firm: {company_name}

## General Guidelines for Responding

{legal_guidelines}{timeline_section}{highlights_section}"""

    context = {
        "matter": matter,
        "prompt_text": prompt_text,
    }

    return render(request, "case/ai/prompt.html", context)


@login_required
def chat_upload(request, conv_id):
    """Handle file upload to chat conversation."""
    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter__in=get_accessible_matters()
    )

    if request.method != "POST":
        return HttpResponse(status=405)

    uploaded_file = request.FILES.get("file")
    if not uploaded_file:
        return HttpResponse(status=400)

    # Validate file extension (PDFs only)
    filename = uploaded_file.name
    if not filename.lower().endswith(".pdf"):
        return render(
            request,
            "case/ai/attachments.html",
            {
                "conversation": conversation,
                "error": "Only PDF files are allowed",
            },
        )

    # Create the attachment
    attachment = ChatAttachment.objects.create(
        conversation=conversation,
        file=uploaded_file,
        filename=filename,
        ocr_status="pending",
    )

    # Start background OCR processing
    thread = threading.Thread(
        target=process_chat_attachment_ocr,
        args=(attachment.id,),
        daemon=True,
    )
    thread.start()

    # Return updated attachments list
    return render(
        request,
        "case/ai/attachments.html",
        {
            "conversation": conversation,
            "attachments": conversation.attachments.all(),
        },
    )


@login_required
def chat_attachment_status(request, conv_id):
    """Return current attachment status for polling."""
    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter__in=get_accessible_matters()
    )

    return render(
        request,
        "case/ai/attachments.html",
        {
            "conversation": conversation,
            "attachments": conversation.attachments.all(),
        },
    )


@login_required
def delete_attachment(request, attachment_id):
    """Delete a chat attachment."""
    attachment = get_object_or_404(
        ChatAttachment,
        pk=attachment_id,
        conversation__matter__in=get_accessible_matters(),
    )

    conversation = attachment.conversation
    attachment.file.delete()  # Delete the file from storage
    attachment.delete()

    # Return updated attachments list
    return render(
        request,
        "case/ai/attachments.html",
        {
            "conversation": conversation,
            "attachments": conversation.attachments.all(),
        },
    )


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
    from .selector import build_manifest, estimate_tokens

    matter, _ = get_matter_from_url(request, matter_id)

    # Resolve jurisdiction
    company = Company.objects.first()
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
        estimate_tokens(content_map[(item.item_type, item.item_id)])
        for item in manifest_items
        if (item.item_type, item.item_id) in content_map
    )

    total_tokens = baseline_tokens + auto_pool_tokens

    # --- Cost estimates per model ---
    model_costs = [
        {"name": "Gemini 2.5 Flash", "input_price": 0.15, "context_limit": 1_000_000},
        {"name": "Gemini 2.5 Pro", "input_price": 1.25, "context_limit": 1_000_000},
        {
            "name": "Gemini Pro (Latest)",
            "input_price": 2.00,
            "context_limit": 1_000_000,
        },
        {"name": "Claude Sonnet 4", "input_price": 3.00, "context_limit": 200_000},
        {"name": "Claude Opus 4.5", "input_price": 15.00, "context_limit": 200_000},
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
