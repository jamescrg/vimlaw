"""
Views for AI chat within case analysis.
"""

import logging
import threading
import time
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.case.models import Fact, Highlight
from apps.case.views import get_matter_from_url
from apps.matters.models import Matter
from apps.outlines.models import Outline

from .context import assemble_matter_context
from .models import ChatAttachment, Conversation, Message
from .tasks import process_ai_request, process_chat_attachment_ocr

logger = logging.getLogger(__name__)


def get_accessible_matters():
    """Get all matters accessible to logged-in users (currently all open matters)."""
    return Matter.objects.filter(status="Open")


@login_required
def ai_index(request, matter_id):
    """Main AI view - list of conversations."""
    matter, matters = get_matter_from_url(request, matter_id)

    conversations = Conversation.objects.filter(matter=matter)

    context = {
        "app": "documents",
        "subapp": "ai",
        "matter": matter,
        "matters": matters,
        "conversations": conversations,
    }

    return render(request, "case/ai/main.html", context)


@login_required
def ai_list(request, matter_id):
    """Return conversation list partial (for HTMX refresh)."""
    matter, _ = get_matter_from_url(request, matter_id)

    conversations = Conversation.objects.filter(matter=matter)

    return render(
        request,
        "case/ai/list.html",
        {
            "conversations": conversations,
            "matter": matter,
        },
    )


@login_required
def conversation_view(request, conv_id):
    """Standalone full-height view for a single conversation."""
    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter__in=get_accessible_matters()
    )
    matter = conversation.matter

    messages = conversation.messages.all()

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
    llm = request.GET.get("llm", "claude")
    if llm not in ["claude", "gemini-flash", "gemini-pro"]:
        llm = "claude"

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

    messages = conversation.messages.all() if conversation else []

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
    llm = request.POST.get("llm", "claude")

    if not user_message:
        return HttpResponse(status=400)

    # Validate llm
    if llm not in ["claude", "gemini-flash", "gemini-pro"]:
        llm = "claude"

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

    # Assemble context and get chat history for AI (include user for identity)
    context_text = assemble_matter_context(
        matter, user=request.user, conversation=conversation
    )

    # Build chat history with user names for multi-participant context
    chat_history = []
    for msg in conversation.messages.select_related("user"):
        entry = {"role": msg.role, "content": msg.content}
        if msg.role == "user" and msg.user:
            entry["user_name"] = msg.user.get_full_name() or msg.user.username
        chat_history.append(entry)

    # Initialize status in cache
    cache_key = f"ai_status_{conversation.id}"
    cache.set(
        cache_key,
        {"status": "starting", "message": "Starting..."},
        timeout=600,
    )

    # Start background thread for AI processing
    thread = threading.Thread(
        target=process_ai_request,
        args=(conversation.id, context_text, chat_history, conversation.llm),
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
        # Save assistant message
        assistant_message = Message.objects.create(
            conversation=conversation,
            role="assistant",
            content=status_data["response"],
            input_tokens=status_data.get("input_tokens"),
            output_tokens=status_data.get("output_tokens"),
        )

        # Update conversation timestamp
        conversation.save()

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

    messages = conversation.messages.all()

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
def create_prompt(request, matter_id):
    """Generate a prompt stuffing document for external AI chat clients."""
    matter, _ = get_matter_from_url(request, matter_id)

    # Load ai-prompt.md content
    legal_md_path = Path(settings.BASE_DIR) / "docs" / "ai-prompt.md"
    try:
        legal_guidelines = legal_md_path.read_text()
    except FileNotFoundError:
        legal_guidelines = "(Guidelines file not found)"

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

    # Build outlines section
    def format_outline_items(items, depth=0):
        """Recursively format outline items with indentation."""
        lines = []
        for item in items:
            indent = "  " * depth
            content = item.content.strip() if item.content else "(empty)"
            if item.heading:
                lines.append(f"{indent}**{content}**")
            else:
                lines.append(f"{indent}- {content}")
            # Recursively add children
            children = item.get_children()
            if children:
                lines.extend(format_outline_items(children, depth + 1))
        return lines

    outlines = Outline.objects.filter(matter=matter).order_by("-importance", "-date")
    outline_blocks = []
    for outline in outlines:
        block_lines = [f"### {outline.title} ({outline.date})"]
        root_items = outline.get_root_items()
        if root_items:
            block_lines.append("")  # blank line after header
            block_lines.extend(format_outline_items(root_items))
        outline_blocks.append("\n".join(block_lines))

    outlines_section = ""
    if outline_blocks:
        outlines_section = (
            "\n\n## Attorney Notes\n\n"
            "The following are attorney notes and research outlines "
            "for this matter:\n\n" + "\n\n".join(outline_blocks)
        )

    # Build the prompt text with proper markdown formatting
    prompt_text = f"""## Request Date

{date.today().strftime("%B %d, %Y")}

## Requesting Party

- Name: {user.get_full_name()}
- Email: {user.email}
- Role: {role_description}
- Law Firm: Craig Legal, LLC

## General Guidelines for Responding

{legal_guidelines}{timeline_section}{highlights_section}{outlines_section}"""

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
