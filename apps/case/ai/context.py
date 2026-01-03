"""
Context assembly for AI chat.

Gathers matter data for the system prompt, organized by importance:
1. Matter overview, contacts, proceedings (always included)
2. Critical evidence (importance 1-2) - across all content types
3. High importance (importance 3-4) - across all content types
4. Medium importance (importance 5-6) - across all content types
5. Reference materials (importance 7+) - across all content types
6. Administrative info (tasks, events, settlement)

Content types with importance ratings:
- Documents, Highlights, Facts, Notes, Case Law
- Reference Conversations (automatically HIGH importance since explicitly flagged)

Time entries are excluded per user request.
"""

import logging
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path

from django.conf import settings

from apps.agenda.events.models import Event
from apps.agenda.tasks.models import Task
from apps.case.models import CaseLaw, Document, Fact, Highlight
from apps.matters.models import Relationship
from apps.matters.proceedings.models import Proceeding
from apps.matters.settlement.models import SettlementEntry
from apps.notes.models import Note

from .models import Conversation

logger = logging.getLogger(__name__)

# Path to the legal AI instructions file
LEGAL_PROMPT_FILE = Path(settings.BASE_DIR) / "docs" / "ai-prompt.md"


class ImportanceTier(Enum):
    """Importance tiers for context items."""

    CRITICAL = "CRITICAL"  # Importance 1-2
    HIGH = "HIGH"  # Importance 3-4
    MEDIUM = "MEDIUM"  # Importance 5-6
    REFERENCE = "REFERENCE"  # Importance 7+


def get_importance_tier(importance: int) -> ImportanceTier:
    """Map importance value (1-10) to a tier."""
    if importance <= 2:
        return ImportanceTier.CRITICAL
    elif importance <= 4:
        return ImportanceTier.HIGH
    elif importance <= 6:
        return ImportanceTier.MEDIUM
    else:
        return ImportanceTier.REFERENCE


def get_importance_label(importance: int) -> str:
    """Get display label for importance value."""
    tier = get_importance_tier(importance)
    return f"[{tier.value}]"


# Type icons for context items
TYPE_ICONS = {
    "document": "📄",
    "highlight": "🔍",
    "fact": "📅",
    "note": "📝",
    "caselaw": "⚖️",
    "conversation": "💬",
}


@dataclass
class ContextItem:
    """A single item to include in context, with importance and type info."""

    importance: int
    item_type: str  # "document", "highlight", "fact", "note", "caselaw", "conversation"
    content: str
    source_id: int  # For reference

    @property
    def tier(self) -> ImportanceTier:
        return get_importance_tier(self.importance)

    @property
    def label(self) -> str:
        return get_importance_label(self.importance)

    @property
    def icon(self) -> str:
        return TYPE_ICONS.get(self.item_type, "•")

    def format(self) -> str:
        """Format this item for context output."""
        return f"{self.label} {self.icon} {self.content}"


def collect_context_items(matter, current_conversation=None) -> list[ContextItem]:
    """
    Collect all items with importance ratings from the matter.

    Args:
        matter: The Matter object
        current_conversation: Optional current Conversation to exclude from references

    Returns a list of ContextItem objects sorted by importance (most important first).
    """
    items = []

    # Collect Documents
    for doc in Document.objects.filter(matter=matter).select_related():
        content_parts = [f"**Document: {doc.name}** ({doc.category})"]
        if doc.date:
            content_parts[0] += f" - {doc.date}"
        if doc.description:
            content_parts.append(f"Description: {doc.description}")
        if doc.ocr_text and doc.ocr_status in ["completed", "extracted"]:
            excerpt = doc.ocr_text[:1500].strip()
            if len(doc.ocr_text) > 1500:
                excerpt += "..."
            content_parts.append(f"Content: {excerpt}")

        items.append(
            ContextItem(
                importance=doc.importance,
                item_type="document",
                content="\n".join(content_parts),
                source_id=doc.id,
            )
        )

    # Collect Highlights
    for hl in Highlight.objects.filter(document__matter=matter).select_related(
        "document"
    ):
        text_preview = hl.text[:500] if hl.text else ""
        if hl.text and len(hl.text) > 500:
            text_preview += "..."

        content = f'**Highlight:** "{text_preview}" — {hl.citation}'
        if hl.slug:
            content = f'**Highlight ({hl.slug}):** "{text_preview}" — {hl.citation}'

        items.append(
            ContextItem(
                importance=hl.importance,
                item_type="highlight",
                content=content,
                source_id=hl.id,
            )
        )

    # Collect Facts (Timeline)
    for fact in Fact.objects.filter(matter=matter).prefetch_related(
        "documents", "highlights"
    ):
        content = f"**Fact [{fact.date}]:** {fact.description}"

        # Add source references
        sources = []
        for doc in fact.documents.all()[:2]:
            sources.append(doc.citation)
        for hl in fact.highlights.all()[:2]:
            sources.append(hl.citation)
        if sources:
            content += f" (Sources: {', '.join(sources)})"

        items.append(
            ContextItem(
                importance=fact.importance,
                item_type="fact",
                content=content,
                source_id=fact.id,
            )
        )

    # Collect Notes (always CRITICAL - user-created notes are high value)
    for note in Note.objects.filter(matter=matter):
        content_parts = [f"**Note: {note.title}**"]
        if note.category:
            content_parts[0] += f" [{note.get_category_display()}]"
        if note.topic:
            content_parts[0] += f" - {note.topic}"
        if note.content:
            # Limit content length per note
            note_content = note.content[:2000]
            if len(note.content) > 2000:
                note_content += "\n... (truncated)"
            content_parts.append(note_content)

        items.append(
            ContextItem(
                importance=1,  # Always CRITICAL for notes
                item_type="note",
                content="\n".join(content_parts),
                source_id=note.id,
            )
        )

    # Collect Case Law (default to importance 3 = HIGH since intentionally researched)
    for caselaw in CaseLaw.objects.filter(matter=matter):
        content_parts = [f"**Case Law: {caselaw.case_name}**, {caselaw.citation}"]
        if caselaw.court:
            content_parts.append(f"Court: {caselaw.court}")
        if caselaw.date_filed:
            content_parts.append(f"Date: {caselaw.date_filed}")
        if caselaw.notes:
            content_parts.append(f"Notes: {caselaw.notes[:500]}")
        if caselaw.text:
            content_parts.append(f"Opinion:\n{caselaw.text}")

        items.append(
            ContextItem(
                importance=3,  # Default to HIGH for case law
                item_type="caselaw",
                content="\n".join(content_parts),
                source_id=caselaw.id,
            )
        )

    # Collect Reference Conversations (importance 3 = HIGH since explicitly flagged)
    reference_convos = Conversation.objects.filter(
        matter=matter, is_reference=True
    ).order_by("-updated_at")
    if current_conversation:
        reference_convos = reference_convos.exclude(id=current_conversation.id)

    for conv in reference_convos:
        content_parts = [
            f"**Reference Conversation: {conv.title or 'Untitled'}**",
            f"Date: {conv.updated_at.strftime('%b %d, %Y')}",
        ]

        # Include messages from reference conversation (limit per conversation)
        messages = conv.messages.select_related("user").order_by("created_at")
        msg_lines = []
        total_chars = 0
        max_chars = 3000

        for msg in messages:
            if msg.role == "user":
                user_name = msg.user.get_full_name() if msg.user else "User"
                msg_line = f"**{user_name}:** {msg.content}"
            else:
                msg_line = f"**Assistant:** {msg.content}"

            # Truncate long messages
            if len(msg_line) > 1000:
                msg_line = msg_line[:1000] + "... (truncated)"

            if total_chars + len(msg_line) > max_chars:
                msg_lines.append("... (remaining messages omitted)")
                break

            msg_lines.append(msg_line)
            total_chars += len(msg_line)

        if msg_lines:
            content_parts.append("\n".join(msg_lines))

        items.append(
            ContextItem(
                importance=3,  # HIGH importance for reference conversations
                item_type="conversation",
                content="\n".join(content_parts),
                source_id=conv.id,
            )
        )

    # Sort by importance (lowest number = most important)
    items.sort(key=lambda x: x.importance)

    return items


def format_items_by_tier(items: list[ContextItem], tier: ImportanceTier) -> str:
    """Format all items of a specific importance tier."""
    tier_items = [item for item in items if item.tier == tier]

    if not tier_items:
        return "No items in this category."

    lines = [item.format() for item in tier_items]
    return "\n\n".join(lines)


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
## Critical Evidence & Information
Items marked [CRITICAL] are the most important to the case.

{critical_items}

## High Importance Materials
Items marked [HIGH] are significant to the case. This includes reference conversations.

{high_items}

## Supporting Materials
Items marked [MEDIUM] provide supporting context.

{medium_items}

## Reference Materials
Items marked [REFERENCE] are background information.

{reference_items}

## Administrative Information

### Tasks
{tasks}

### Upcoming Events
{events}

### Settlement Information
{settlement}
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
    Assemble context from all matter data, organized by importance.

    Args:
        matter: The Matter object to assemble context for
        user: The requesting user (for request info section)
        conversation: Optional Conversation object to include chat attachments

    Structure:
    1. Matter overview, contacts, proceedings (always included)
    2. Chat attachments (if provided)
    3. Items organized by importance tier (CRITICAL, HIGH, MEDIUM, REFERENCE)
    4. Administrative info (tasks, events, settlement)
    """
    sections = {}

    # Matter Overview
    sections["matter_overview"] = format_matter_overview(matter)

    # Contacts
    sections["contacts"] = format_contacts(matter)

    # Proceedings
    sections["proceedings"] = format_proceedings(matter)

    # Chat attachments (if conversation provided)
    if conversation:
        sections["chat_attachments"] = format_chat_attachments(conversation)
    else:
        sections["chat_attachments"] = ""

    # Collect all importance-rated items and format by tier
    all_items = collect_context_items(matter, current_conversation=conversation)

    sections["critical_items"] = format_items_by_tier(
        all_items, ImportanceTier.CRITICAL
    )
    sections["high_items"] = format_items_by_tier(all_items, ImportanceTier.HIGH)
    sections["medium_items"] = format_items_by_tier(all_items, ImportanceTier.MEDIUM)
    sections["reference_items"] = format_items_by_tier(
        all_items, ImportanceTier.REFERENCE
    )

    # Tasks
    sections["tasks"] = format_tasks(matter)

    # Events
    sections["events"] = format_events(matter)

    # Settlement
    sections["settlement"] = format_settlement(matter)

    # Build the full system prompt
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


def format_tasks(matter) -> str:
    """Format tasks, pending first."""
    tasks = Task.objects.filter(matter=matter).order_by(
        "date_completed", "priority", "date_due"
    )[:20]

    if not tasks:
        return "No tasks."

    lines = []
    for task in tasks:
        status_icon = "[DONE]" if task.date_completed else "[PENDING]"
        line = f"- {status_icon} P{task.priority}: {task.description}"
        if task.date_due:
            line += f" (Due: {task.date_due})"
        lines.append(line)

    return "\n".join(lines)


def format_events(matter) -> str:
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
    for event in all_events:
        line = f"- [{event.date}] {event.description}"
        if event.party:
            line += f" with {event.party}"
        if event.location:
            line += f" ({event.location})"
        lines.append(line)

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


def format_chat_attachments(conversation) -> str:
    """Format chat attachment content for AI context."""
    attachments = conversation.attachments.filter(ocr_status="completed")

    if not attachments:
        return ""

    lines = [
        "\n## Chat Attachments",
        "\nThe following files were uploaded to this conversation:\n",
    ]

    for attachment in attachments:
        lines.append(f"\n### {attachment.filename}\n")

        # Include OCR text content (limit per attachment)
        if attachment.ocr_text:
            content = attachment.ocr_text[:3000]
            if len(attachment.ocr_text) > 3000:
                content += "\n... (content truncated)"
            lines.append(content)

    return "\n".join(lines)
