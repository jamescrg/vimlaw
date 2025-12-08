"""
Context assembly for AI chat.

Gathers matter data for the system prompt with priority:
1. Matter overview, contacts, proceedings (always included)
2. Outlines - Full hierarchical content with sources (highest priority)
3. Highlights - Annotated document excerpts with citations
4. Documents - OCR text excerpts (ranked by importance)
5. Timeline facts, tasks, events, settlement (budget-limited)

Time entries are excluded per user request.
"""

import logging
from pathlib import Path

from django.conf import settings

from apps.agenda.events.models import Event
from apps.agenda.tasks.models import Task
from apps.case.models import Document, Fact, Highlight
from apps.matters.models import Relationship
from apps.matters.proceedings.models import Proceeding
from apps.matters.settlement.models import SettlementEntry
from apps.outlines.models import Outline

logger = logging.getLogger(__name__)

# Token budget allocation (approximate, assuming ~4 chars per token)
MAX_CONTEXT_CHARS = 80000  # ~20k tokens for context, leaving room for conversation

# Path to the legal AI instructions file
LEGAL_PROMPT_FILE = Path(settings.BASE_DIR) / "docs" / "ai-prompt.md"

MATTER_CONTEXT_TEMPLATE = """
## Current Matter: {matter_name}

## Matter Overview
{matter_overview}

## Contacts & Parties
{contacts}

## Court Proceedings
{proceedings}

## Outlines & Notes
{outlines}

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


def assemble_matter_context(matter) -> str:
    """
    Assemble context from all matter data, respecting token limits.

    Priority for context inclusion:
    1. Matter overview (always included)
    2. Contacts (always included)
    3. Proceedings (always included)
    4. Outlines (highest priority user content)
    5. Highlights (second priority)
    6. Documents (third priority, by importance)
    7. Timeline facts (by importance)
    8. Tasks (pending first)
    9. Events (upcoming first)
    10. Settlement info
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

    # 4. Outlines (highest priority - user notes and research)
    budget_outlines = min(remaining_budget // 3, 25000)
    outlines = format_outlines(matter, budget_outlines)
    sections["outlines"] = outlines
    remaining_budget -= len(outlines)

    # 5. Highlights (second priority)
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

    # Build the full system prompt:
    # 1. Load legal instructions from docs/ai-prompt.md (read fresh each time)
    # 2. Append matter-specific context
    legal_prompt = load_legal_prompt()
    matter_context = MATTER_CONTEXT_TEMPLATE.format(matter_name=matter.name, **sections)

    return f"{legal_prompt}\n\n---\n{matter_context}"


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


def format_outlines(matter, budget: int) -> str:
    """Format outlines with hierarchical content (highest priority)."""
    outlines = Outline.objects.filter(matter=matter).order_by("-importance", "-date")

    if not outlines:
        return "No outlines or notes."

    lines = []
    char_count = 0

    for outline in outlines:
        header = f"\n### {outline.title}"
        if outline.date:
            header += f" ({outline.date})"

        if char_count + len(header) > budget:
            lines.append("\n... (additional outlines omitted for brevity)")
            break

        lines.append(header)
        char_count += len(header)

        # Get outline items in hierarchical order
        items = format_outline_items(outline, budget - char_count)
        lines.append(items)
        char_count += len(items)

        if char_count > budget:
            break

    return "\n".join(lines) if lines else "No outlines."


def format_outline_items(outline, budget: int) -> str:
    """Format outline items with indentation for hierarchy."""
    root_items = outline.get_root_items()
    lines = []
    char_count = 0

    def format_item_recursive(item, depth=0):
        nonlocal char_count
        if char_count > budget:
            return

        indent = "  " * depth
        prefix = "- " if not item.heading else "## "
        content = item.content.strip() if item.content else "(empty)"

        line = f"{indent}{prefix}{content}"

        # Add source references if any
        sources = []
        for doc in item.documents.all()[:3]:
            sources.append(f"[Doc: {doc.name}]")
        for hl in item.highlights.all()[:3]:
            sources.append(f"[Highlight: {hl.slug}]")
        if sources:
            line += " " + " ".join(sources)

        if char_count + len(line) > budget:
            return

        lines.append(line)
        char_count += len(line) + 1

        # Recurse for children
        for child in item.get_children():
            format_item_recursive(child, depth + 1)

    for item in root_items:
        format_item_recursive(item)
        if char_count > budget:
            break

    return "\n".join(lines)


def format_highlights(matter, budget: int) -> str:
    """Format document highlights (second priority)."""
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
