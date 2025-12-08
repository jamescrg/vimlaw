"""
Views for AI chat within case analysis.
"""

import logging
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.case.documents.get_document_data import get_selected_matter

from .anthropic_client import send_to_claude
from .context import assemble_matter_context
from .models import Conversation, Message

logger = logging.getLogger(__name__)


@login_required
def ai_index(request):
    """Main AI view - list of conversations."""
    matter, matters = get_selected_matter(request)

    if not matter:
        return render(
            request,
            "case/ai/main.html",
            {
                "app": "documents",
                "subapp": "ai",
                "matter": None,
                "matters": matters,
                "conversations": [],
            },
        )

    conversations = Conversation.objects.filter(matter=matter, user=request.user)

    context = {
        "app": "documents",
        "subapp": "ai",
        "matter": matter,
        "matters": matters,
        "conversations": conversations,
    }

    return render(request, "case/ai/main.html", context)


@login_required
def ai_list(request):
    """Return conversation list partial (for HTMX refresh)."""
    matter, _ = get_selected_matter(request)

    if not matter:
        return render(request, "case/ai/list.html", {"conversations": []})

    conversations = Conversation.objects.filter(matter=matter, user=request.user)

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
    matter, _ = get_selected_matter(request)

    if not matter:
        return redirect("case:ai-index")

    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter=matter, user=request.user
    )

    messages = conversation.messages.all()

    context = {
        "matter": matter,
        "conversation": conversation,
        "messages": messages,
    }

    return render(request, "case/ai/conversation-standalone.html", context)


@login_required
def message_list(request):
    """Return message list partial (for HTMX refresh)."""
    matter, _ = get_selected_matter(request)
    conversation_id = request.GET.get("conversation_id")

    if not matter:
        return render(request, "case/ai/messages.html", {"messages": []})

    if conversation_id:
        conversation = get_object_or_404(
            Conversation, pk=conversation_id, matter=matter, user=request.user
        )
    else:
        conversation = Conversation.objects.filter(
            matter=matter, user=request.user
        ).first()

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
def send_message(request):
    """Handle user message submission and get AI response."""
    matter, _ = get_selected_matter(request)

    if not matter:
        return HttpResponse(status=400)

    if request.method != "POST":
        return HttpResponse(status=405)

    user_message = request.POST.get("message", "").strip()
    conversation_id = request.POST.get("conversation_id")

    if not user_message:
        return HttpResponse(status=400)

    # Get or create conversation
    if conversation_id:
        conversation = get_object_or_404(
            Conversation, pk=conversation_id, matter=matter, user=request.user
        )
    else:
        conversation = Conversation.objects.create(
            matter=matter, user=request.user, title=user_message[:50]
        )

    # Update title if this is first message and title is default
    if conversation.title == "New Conversation":
        conversation.title = user_message[:50]
        if len(user_message) > 50:
            conversation.title += "..."
        conversation.save()

    # Save user message
    Message.objects.create(conversation=conversation, role="user", content=user_message)

    # Assemble context and get AI response
    context_text = assemble_matter_context(matter)
    chat_history = list(conversation.messages.values("role", "content"))

    try:
        response_text, input_tokens, output_tokens = send_to_claude(
            context_text, chat_history
        )

        # Save assistant message
        Message.objects.create(
            conversation=conversation,
            role="assistant",
            content=response_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        # Update conversation timestamp
        conversation.save()

    except Exception as e:
        logger.exception("Error calling Claude API")
        # Save error as assistant message
        Message.objects.create(
            conversation=conversation,
            role="assistant",
            content=f"Error: Unable to get response. {str(e)}",
        )

    # Return updated message list
    return render(
        request,
        "case/ai/messages.html",
        {
            "messages": conversation.messages.all(),
            "conversation": conversation,
            "matter": matter,
        },
    )


@login_required
def conversation_list(request):
    """Return conversation list partial."""
    matter, _ = get_selected_matter(request)

    if not matter:
        return render(request, "case/ai/conversation-list.html", {"conversations": []})

    conversations = Conversation.objects.filter(matter=matter, user=request.user)

    return render(
        request,
        "case/ai/conversation-list.html",
        {
            "conversations": conversations,
            "matter": matter,
        },
    )


@login_required
def new_conversation(request):
    """Create a new conversation and return its URL for opening in new tab."""
    matter, _ = get_selected_matter(request)

    if not matter:
        return redirect("case:ai-index")

    conversation = Conversation.objects.create(
        matter=matter, user=request.user, title="New Conversation"
    )

    # Return the URL for the JS to open in new tab, and trigger list refresh
    response = HttpResponse(f"/case/ai/conversations/{conversation.id}/view/")
    response["HX-Trigger"] = "conversationsChanged"
    return response


@login_required
def select_conversation(request, conv_id):
    """Switch to a different conversation."""
    matter, _ = get_selected_matter(request)

    if not matter:
        return redirect("case:ai-index")

    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter=matter, user=request.user
    )

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
    matter, _ = get_selected_matter(request)

    if not matter:
        return redirect("case:ai-index")

    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter=matter, user=request.user
    )

    conversation.delete()

    # Trigger refresh of conversation list
    response = HttpResponse(status=204)
    response["HX-Trigger"] = "conversationsChanged"
    return response


@login_required
def rename_conversation(request, conv_id):
    """Rename a conversation - POST saves and returns list or title."""
    matter, _ = get_selected_matter(request)

    if not matter:
        return HttpResponse(status=400)

    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter=matter, user=request.user
    )

    if request.method == "POST":
        new_title = request.POST.get("title", "").strip()
        if new_title:
            conversation.title = new_title[:255]
            conversation.save()

        # Check if request came from list view or standalone view
        if request.headers.get("HX-Target") == "conversationTitle":
            # From standalone view - return title partial
            return render(
                request,
                "case/ai/conversation-title.html",
                {
                    "conversation": conversation,
                },
            )
        else:
            # From list view - return updated list
            conversations = Conversation.objects.filter(
                matter=matter, user=request.user
            )
            return render(
                request,
                "case/ai/list.html",
                {
                    "conversations": conversations,
                    "matter": matter,
                },
            )

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
    """Return rename form for list view."""
    matter, _ = get_selected_matter(request)

    if not matter:
        return HttpResponse(status=400)

    conversation = get_object_or_404(
        Conversation, pk=conv_id, matter=matter, user=request.user
    )

    conversations = Conversation.objects.filter(matter=matter, user=request.user)

    return render(
        request,
        "case/ai/list-rename.html",
        {
            "conversations": conversations,
            "editing_conversation": conversation,
            "matter": matter,
        },
    )


@login_required
def create_prompt(request):
    """Generate a prompt stuffing document for external AI chat clients."""
    matter, _ = get_selected_matter(request)

    if not matter:
        return redirect("case:ai-index")

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

    # Build the prompt text with proper markdown formatting
    prompt_text = f"""## Request Date

{date.today().strftime("%B %d, %Y")}

## Requesting Party

- Name: {user.get_full_name()}
- Email: {user.email}
- Role: {role_description}
- Law Firm: Craig Legal, LLC

## General Guidelines for Responding

{legal_guidelines}"""

    context = {
        "matter": matter,
        "prompt_text": prompt_text,
    }

    return render(request, "case/ai/prompt.html", context)
