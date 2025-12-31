"""
Context assembly for AI chat.

Gathers matter data for the system prompt with priority:
1. Matter overview, contacts, proceedings (always included)
2. Notes - Attorney notes and research (highest priority)
3. Highlights - Annotated document excerpts with citations
4. Documents - OCR text excerpts (ranked by importance)
5. Timeline facts, tasks, events, settlement (budget-limited)

Time entries are excluded per user request.
"""

import logging
from datetime import date
from pathlib import Path

from django.conf import settings

from apps.agenda.events.models import Event
from apps.agenda.tasks.models import Task
from apps.case.models import Document, Fact, Highlight
from apps.matters.models import Relationship
from apps.matters.proceedings.models import Proceeding
from apps.matters.settlement.models import SettlementEntry
from apps.notes.models import Note

from .models import Conversation

logger = logging.getLogger(__name__)

# Token budget allocation (approximate, assuming ~4 chars per token)
MAX_CONTEXT_CHARS = 80000  # ~20k tokens for context, leaving room for conversation

# Path to the legal AI instructions file
LEGAL_PROMPT_FILE = Path(settings.BASE_DIR) / "docs" / "ai-prompt.md"

REQUEST_INFO_TEMPLATE = """## Request Date

{request_date}

## Requesting Party

- Name: {user_name}
- Email: {user_email}
- Role: {role_description}
- Law Firm: Craig Legal, LLC
"""

MATTER_CONTEXT_TEMPLATE = """
## Current Matter: {matter_name}

## Matter Overview
{matter_overview}

## Contacts & Parties
{contacts}

## Court Proceedings
{proceedings}
{chat_attachments}
## Attorney Notes
{notes}

## Document Highlights
{highlights}

## Documents
{documents}

## Timeline / Key Facts
{timeline}

## Tasks
{tasks}

## Events
{events}

## Settlement Information
{settlement}

## Previous Conversations
{previous_conversations}
"""


def load_legal_prompt() -> str:
    """
    Load the legal AI instructions from docs/ai-prompt.md.

    This file is read fresh on each call so edits take effect immediately.
    """
    try:
        if LEGAL_PROMPT_FILE.exists():
            return LEGAL_PROMPT_FILE.read_text(encoding="utf-8")
        else:
            logger.warning(f"Legal prompt file not found: {LEGAL_PROMPT_FILE}")
            return "You are a legal assistant. Be accurate and cite sources."
    except Exception as e:
        logger.error(f"Error reading legal prompt file: {e}")
        return "You are a legal assistant. Be accurate and cite sources."


def assemble_matter_context(matter, user=None, conversation=None) -> str:
    """
    Assemble context from all matter data, respecting token limits.

    Args:
        matter: The Matter object to assemble context for
        user: The requesting user (for request info section)
        conversation: Optional Conversation object to include chat attachments

    Priority for context inclusion:
    1. Matter overview (always included)
    2. Contacts (always included)
    3. Proceedings (always included)
    4. Chat attachments (if provided, highest priority for temporary context)
    5. Notes (attorney notes and research)
    6. Highlights (annotated document excerpts)
    7. Documents (by importance)
    8. Timeline facts (by importance)
    9. Tasks (pending first)
    10. Events (upcoming first)
    11. Settlement info
    """
    sections = {}
    remaining_budget = MAX_CONTEXT_CHARS

    # 1. Matter Overview (required)
    overview = format_matter_overview(matter)
    sections["matter_overview"] = overview
    remaining_budget -= len(overview)

    # 2. Contacts (required)
    contacts = format_contacts(matter)
    sections["contacts"] = contacts
    remaining_budget -= len(contacts)

    # 3. Proceedings (required)
    proceedings = format_proceedings(matter)
    sections["proceedings"] = proceedings
    remaining_budget -= len(proceedings)

    # 4. Chat attachments (if conversation provided)
    if conversation:
        budget_attachments = min(remaining_budget // 4, 10000)
        chat_attachments = format_chat_attachments(conversation, budget_attachments)
        sections["chat_attachments"] = chat_attachments
        remaining_budget -= len(chat_attachments)
    else:
        sections["chat_attachments"] = ""

    # 5. Notes (attorney notes and research)
    budget_notes = min(remaining_budget // 3, 25000)
    notes = format_notes(matter, budget_notes)
    sections["notes"] = notes
    remaining_budget -= len(notes)

    # 6. Highlights (annotated document excerpts)
    budget_highlights = min(remaining_budget // 3, 15000)
    highlights = format_highlights(matter, budget_highlights)
    sections["highlights"] = highlights
    remaining_budget -= len(highlights)

    # 6. Documents (third priority, budget-aware)
    budget_docs = min(remaining_budget // 3, 15000)
    documents = format_documents(matter, budget_docs)
    sections["documents"] = documents
    remaining_budget -= len(documents)

    # 7. Timeline (by importance)
    budget_timeline = min(remaining_budget // 4, 10000)
    timeline = format_timeline(matter, budget_timeline)
    sections["timeline"] = timeline
    remaining_budget -= len(timeline)

    # 8. Tasks
    budget_tasks = min(remaining_budget // 3, 5000)
    tasks = format_tasks(matter, budget_tasks)
    sections["tasks"] = tasks
    remaining_budget -= len(tasks)

    # 9. Events
    budget_events = min(remaining_budget // 2, 5000)
    events = format_events(matter, budget_events)
    sections["events"] = events
    remaining_budget -= len(events)

    # 10. Settlement
    settlement = format_settlement(matter)
    sections["settlement"] = settlement

    # 11. Previous Conversations (summaries + flagged reference conversations)
    budget_conversations = min(remaining_budget, 15000)
    previous_conversations = format_previous_conversations(
        matter, conversation, budget_conversations
    )
    sections["previous_conversations"] = previous_conversations

    # Build the full system prompt:
    # 1. Request info (date and requesting party)
    # 2. Load legal instructions from docs/ai-prompt.md (read fresh each time)
    # 3. Append matter-specific context
    request_info = ""
    if user:
        if user.is_attorney:
            role_description = f"{user.get_full_name()} is an attorney"
        else:
            role_description = (
                f"{user.get_full_name()} is a paralegal supporting an attorney"
            )
        request_info = REQUEST_INFO_TEMPLATE.format(
            request_date=date.today().strftime("%B %d, %Y"),
            user_name=user.get_full_name(),
            user_email=user.email,
            role_description=role_description,
        )

    legal_prompt = load_legal_prompt()
    matter_context = MATTER_CONTEXT_TEMPLATE.format(matter_name=matter.name, **sections)

    return f"{request_info}{legal_prompt}\n\n---\n{matter_context}"


def format_matter_overview(matter) -> str:
    """Format basic matter information."""
    lines = [
        f"Name: {matter.name}",
        f"Status: {matter.status}",
        f"Work Status: {matter.work_status or 'Not set'}",
        f"Practice Area: {matter.practice_area.name if matter.practice_area else 'Not specified'}",
        f"Description: {matter.description or 'No description'}",
        f"Start Date: {matter.date_start}",
        f"Client Reference: {matter.client_reference_id or 'None'}",
    ]
    if matter.client:
        lines.append(f"Primary Client: {matter.client.name}")
    return "\n".join(lines)


def format_contacts(matter) -> str:
    """Format contacts and their roles."""
    relationships = Relationship.objects.filter(matter=matter).select_related(
        "contact", "role", "group"
    )

    if not relationships:
        return "No contacts assigned."

    lines = []
    for rel in relationships:
        contact = rel.contact
        role_name = rel.role.name if rel.role else "No role"
        line = f"- {contact.name} ({role_name})"
        if contact.company:
            line += f" - {contact.company}"
        if contact.email:
            line += f" [{contact.email}]"
        lines.append(line)

    return "\n".join(lines)


def format_proceedings(matter) -> str:
    """Format court proceedings."""
    proceedings = Proceeding.objects.filter(matter=matter)

    if not proceedings:
        return "No court proceedings."

    lines = []
    for proc in proceedings:
        primary = " [PRIMARY]" if proc.primary else ""
        lines.append(
            f"- {proc.forum}: Case #{proc.case_number}{primary}\n"
            f"  Filed: {proc.date_filed}, Status: {proc.status}"
        )

    return "\n".join(lines)


def format_notes(matter, budget: int) -> str:
    """Format attorney notes and research (highest priority user content)."""
    notes = Note.objects.filter(matter=matter).order_by("-importance", "-updated_at")

    if not notes:
        return "No attorney notes."

    lines = []
    char_count = 0

    for note in notes:
        # Note header with category and title
        header = f"\n### {note.title}"
        if note.category:
            header += f" [{note.get_category_display()}]"
        if note.topic:
            header += f" - {note.topic}"

        if char_count + len(header) > budget:
            lines.append("\n... (additional notes omitted for brevity)")
            break

        lines.append(header)
        char_count += len(header)

        # Include note content (markdown)
        if note.content:
            # Limit content per note to leave room for others
            content_limit = min(2000, budget - char_count)
            content = note.content[:content_limit]
            if len(note.content) > content_limit:
                content += "\n... (content truncated)"

            lines.append(content)
            char_count += len(content)

        if char_count > budget:
            break

    return "\n".join(lines) if lines else "No attorney notes."


def format_highlights(matter, budget: int) -> str:
    """Format document highlights."""
    highlights = (
        Highlight.objects.filter(document__matter=matter)
        .select_related("document")
        .order_by("-importance")[:100]
    )

    if not highlights:
        return "No document highlights."

    lines = []
    char_count = 0

    for hl in highlights:
        # Include document name, page, and highlighted text
        text_preview = hl.text[:300] if hl.text else ""
        if len(hl.text) > 300:
            text_preview += "..."

        line = f'- "{text_preview}" {hl.citation}'

        if char_count + len(line) > budget:
            lines.append("... (additional highlights omitted)")
            break

        lines.append(line)
        char_count += len(line) + 1

    return "\n".join(lines) if lines else "No highlights."


def format_documents(matter, budget: int) -> str:
    """Format document summaries with OCR excerpts (third priority)."""
    documents = Document.objects.filter(matter=matter).order_by("-importance")[:30]

    if not documents:
        return "No documents uploaded."

    lines = []
    char_count = 0

    for doc in documents:
        # Document header
        header = f"\n### {doc.name} ({doc.category})"
        if doc.date:
            header += f" - {doc.date}"

        # Document description
        desc = doc.description or "No description"

        # OCR text excerpt (if available)
        ocr_excerpt = ""
        if doc.ocr_text and doc.ocr_status in ["completed", "extracted"]:
            excerpt = doc.ocr_text[:800].strip()
            if len(doc.ocr_text) > 800:
                excerpt += "..."
            ocr_excerpt = f"\n  Content excerpt: {excerpt}"

        entry = header + f"\n  {desc}" + ocr_excerpt

        if char_count + len(entry) > budget:
            lines.append("\n... (additional documents omitted for brevity)")
            break

        lines.append(entry)
        char_count += len(entry)

    return "\n".join(lines) if lines else "No documents."


def format_timeline(matter, budget: int) -> str:
    """Format timeline facts, prioritizing by importance and date."""
    facts = Fact.objects.filter(matter=matter).order_by("-importance", "-date")[:50]

    if not facts:
        return "No timeline entries."

    lines = []
    char_count = 0

    for fact in facts:
        line = f"- [{fact.date}] {fact.description}"

        # Add source references
        sources = []
        for doc in fact.documents.all()[:2]:
            sources.append(doc.citation)
        for hl in fact.highlights.all()[:2]:
            sources.append(hl.citation)
        if sources:
            line += " Sources: " + ", ".join(sources)

        if char_count + len(line) > budget:
            lines.append("... (additional facts omitted for brevity)")
            break
        lines.append(line)
        char_count += len(line) + 1

    return "\n".join(lines)


def format_tasks(matter, budget: int) -> str:
    """Format tasks, pending first."""
    tasks = Task.objects.filter(matter=matter).order_by(
        "date_completed", "priority", "date_due"
    )[:20]

    if not tasks:
        return "No tasks."

    lines = []
    char_count = 0

    for task in tasks:
        status_icon = "[DONE]" if task.date_completed else "[PENDING]"
        line = f"- {status_icon} P{task.priority}: {task.description}"
        if task.date_due:
            line += f" (Due: {task.date_due})"

        if char_count + len(line) > budget:
            break
        lines.append(line)
        char_count += len(line) + 1

    return "\n".join(lines)


def format_events(matter, budget: int) -> str:
    """Format events, upcoming first."""
    from django.utils import timezone

    # Upcoming events
    events = Event.objects.filter(
        matter=matter, date__gte=timezone.now().date()
    ).order_by("date")[:15]

    # Also get recent past events
    past_events = Event.objects.filter(
        matter=matter, date__lt=timezone.now().date()
    ).order_by("-date")[:5]

    all_events = list(events) + list(past_events)

    if not all_events:
        return "No events scheduled."

    lines = []
    char_count = 0

    for event in all_events:
        line = f"- [{event.date}] {event.description}"
        if event.party:
            line += f" with {event.party}"
        if event.location:
            line += f" ({event.location})"

        if char_count + len(line) > budget:
            break
        lines.append(line)
        char_count += len(line) + 1

    return "\n".join(lines)


def format_settlement(matter) -> str:
    """Format settlement information."""
    entries = SettlementEntry.objects.filter(matter=matter).order_by("-date")

    if not entries:
        return "No settlement information."

    lines = []
    for entry in entries:
        line = f"- [{entry.date}] {entry.type}: ${entry.amount:,.2f}"
        if entry.notes:
            line += f" - {entry.notes}"
        lines.append(line)

    return "\n".join(lines)


def format_chat_attachments(conversation, budget: int) -> str:
    """Format chat attachment content for AI context."""
    attachments = conversation.attachments.filter(ocr_status="completed")

    if not attachments:
        return ""

    lines = [
        "\n## Chat Attachments",
        "\nThe following files were uploaded to this conversation:\n",
    ]
    char_count = 0

    for attachment in attachments:
        header = f"\n### {attachment.filename}\n"

        if char_count + len(header) > budget:
            lines.append("\n... (additional attachments omitted for brevity)")
            break

        lines.append(header)
        char_count += len(header)

        # Include OCR text content
        if attachment.ocr_text:
            text_budget = min(budget - char_count, 3000)  # Max 3k per attachment
            content = attachment.ocr_text[:text_budget]
            if len(attachment.ocr_text) > text_budget:
                content += "\n... (content truncated)"
            lines.append(content)
            char_count += len(content)

        if char_count > budget:
            break

    return "\n".join(lines)


def format_previous_conversations(matter, current_conversation, budget: int) -> str:
    """
    Format previous conversations for AI context.

    Includes:
    1. Brief summaries of recent conversations (title, date, first message preview)
    2. Full content of conversations marked as reference material
    """
    lines = []
    char_count = 0

    # Get all conversations for this matter, excluding the current one
    conversations = Conversation.objects.filter(matter=matter).order_by("-updated_at")
    if current_conversation:
        conversations = conversations.exclude(id=current_conversation.id)

    if not conversations.exists():
        return "No previous conversations in this matter."

    # Separate reference conversations from regular ones
    reference_conversations = conversations.filter(is_reference=True)
    recent_conversations = conversations.filter(is_reference=False)[:10]

    # 1. Include full content of reference conversations (higher priority)
    if reference_conversations.exists():
        lines.append("### Reference Conversations")
        lines.append(
            "The following conversations have been flagged as important reference material:\n"
        )

        for conv in reference_conversations:
            if char_count > budget * 0.7:  # Reserve 30% for summaries
                lines.append("... (additional reference conversations omitted)")
                break

            conv_header = f"\n#### {conv.title or 'Untitled'}"
            conv_header += f" ({conv.updated_at.strftime('%b %d, %Y')})\n"
            lines.append(conv_header)
            char_count += len(conv_header)

            # Include all messages from reference conversation
            messages = conv.messages.select_related("user").order_by("created_at")
            for msg in messages:
                if msg.role == "user":
                    user_name = msg.user.get_full_name() if msg.user else "User"
                    msg_line = f"**{user_name}:** {msg.content}\n"
                else:
                    msg_line = f"**Assistant:** {msg.content}\n"

                # Truncate long messages
                if len(msg_line) > 2000:
                    msg_line = msg_line[:2000] + "... (truncated)\n"

                if char_count + len(msg_line) > budget * 0.7:
                    lines.append("... (remaining messages omitted)")
                    break

                lines.append(msg_line)
                char_count += len(msg_line)

        lines.append("")  # Blank line separator

    # 2. Include summaries of recent non-reference conversations
    if recent_conversations.exists():
        lines.append("### Recent Conversation Summaries")
        lines.append("Brief overview of recent conversations in this matter:\n")

        for conv in recent_conversations:
            if char_count > budget:
                lines.append("... (additional conversations omitted)")
                break

            # Get first user message as preview
            first_msg = conv.messages.filter(role="user").first()
            preview = ""
            if first_msg:
                preview = first_msg.content[:150]
                if len(first_msg.content) > 150:
                    preview += "..."

            msg_count = conv.messages.count()
            summary_line = f"- **{conv.title or 'Untitled'}** "
            summary_line += f"({conv.updated_at.strftime('%b %d, %Y')}, "
            summary_line += f"{msg_count} messages)"
            if preview:
                summary_line += f'\n  First query: "{preview}"'
            summary_line += "\n"

            if char_count + len(summary_line) > budget:
                lines.append("... (additional conversations omitted)")
                break

            lines.append(summary_line)
            char_count += len(summary_line)

    return "\n".join(lines) if lines else "No previous conversations."
