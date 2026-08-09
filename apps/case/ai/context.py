"""
Context assembly for AI chat.

Gathers matter data for the system prompt, organized by importance:
1. Matter overview, contacts, proceedings (always included)
2. Critical evidence (importance 5) - across all content types
3. High importance (importance 4) - across all content types
4. Medium importance (importance 3) - across all content types
5. Reference materials (importance 1-2) - across all content types
6. Administrative info (tasks, events, settlement)

Content types with importance ratings:
- Documents, Highlights, Facts, Notes
- Reference Conversations (automatically HIGH importance since explicitly flagged)
- Case Law (ai_context field controls inclusion)

Documents and Case Law have a three-state ai_context field:
- "always": Always included with full content
- "auto": Included by intelligent selector based on relevance to user's question
- "never": Completely excluded from context

Time entries are included as administrative data with invoice relationships.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.activity.time.models import TimeEntry
from apps.calendar.models import Event
from apps.case.models import CaseLaw, Document, Fact, Highlight
from apps.mail.ai import format_email_thread, group_by_thread
from apps.mail.models import Email
from apps.matters.models import Relationship
from apps.matters.proceedings.models import Proceeding
from apps.matters.settlement.models import SettlementEntry
from apps.notes.models import Note
from apps.settings.models import Firm
from apps.tasks.models import Task

from .models import Conversation

logger = logging.getLogger(__name__)

# Path to the legal AI instructions file
LEGAL_PROMPT_FILE = Path(settings.BASE_DIR) / "docs" / "ai-prompt.md"


class ImportanceTier(Enum):
    """Importance tiers for context items."""

    CRITICAL = "CRITICAL"  # Importance 5 (Highest)
    HIGH = "HIGH"  # Importance 4 (High)
    MEDIUM = "MEDIUM"  # Importance 3 (Normal)
    REFERENCE = "REFERENCE"  # Importance 1-2 (Low/Lowest)


def get_importance_tier(importance: int) -> ImportanceTier:
    """Map importance value (1-5) to a tier."""
    if importance >= 5:
        return ImportanceTier.CRITICAL
    elif importance >= 4:
        return ImportanceTier.HIGH
    elif importance >= 3:
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
    "email": "✉️",
    "library": "📚",
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


def _fetch_caselaw_opinion_text(caselaw) -> str:
    """Fetch full opinion text from CourtListener for a CaseLaw entry.

    Returns the plain text, or empty string if unavailable.
    Uses stored text as fallback for legacy data.
    """
    # Legacy data with stored text
    if caselaw.text and len(caselaw.text) > 500:
        return caselaw.text

    # Fetch from CourtListener
    from apps.case.courtlistener import fetch_cluster, fetch_opinion

    if caselaw.opinion_id:
        opinion = fetch_opinion(caselaw.opinion_id)
        if opinion.found:
            return opinion.plain_text
    elif caselaw.cluster_id:
        cluster = fetch_cluster(caselaw.cluster_id)
        if cluster:
            sub_opinions = cluster.get("sub_opinions", [])
            if sub_opinions:
                try:
                    oid = int(sub_opinions[0].rstrip("/").split("/")[-1])
                    opinion = fetch_opinion(oid)
                    if opinion.found:
                        return opinion.plain_text
                except (ValueError, IndexError):
                    pass

    return ""


def collect_context_items(
    matter,
    current_conversation=None,
    since=None,
    include_auto=False,
    include_library_always=False,
) -> list[ContextItem]:
    """
    Collect items that are always included in context (ai_context="always"
    for Documents/CaseLaw, plus all Highlights, Facts, Notes, Conversations).

    Items with ai_context="auto" are handled by the selector in selector.py.
    Items with ai_context="never" are excluded entirely.

    Args:
        matter: The Matter object
        current_conversation: Optional current Conversation to exclude from references
        since: Optional datetime — only include items updated at or after it
            (used by the nightly auto-summary to build an incremental delta)
        include_auto: Include ai_context="auto" Documents/Notes/CaseLaw with
            full content instead of leaving them to the selector
        include_library_always: Include ai_context="always" firm-library notes
            (standalone notes in AI-library folders). Off by default so the
            nightly auto-summary and baseline assembly stay matter-only.

    Returns a list of ContextItem objects sorted by importance (most important first).
    """
    items = []

    docs = Document.objects.filter(matter=matter).exclude(ai_context="never")
    if since:
        docs = docs.filter(updated_at__gte=since)

    # Collect Documents — only "always" items get full content here
    for doc in docs:
        if doc.ai_context == "auto" and not include_auto:
            continue  # Handled by selector

        # ai_context="always" — include full content
        content_parts = [f"**Document [doc:{doc.id}]: {doc.name}** ({doc.category})"]
        if doc.date:
            content_parts[0] += f" - {doc.date}"
        if doc.description:
            content_parts.append(f"Description: {doc.description}")
        if doc.ocr_text and doc.ocr_status in ["completed", "extracted"]:
            content_parts.append(f"Content:\n{doc.ocr_text}")

        items.append(
            ContextItem(
                importance=doc.importance,
                item_type="document",
                content="\n".join(content_parts),
                source_id=doc.id,
            )
        )

    # Collect Highlights (always included — no ai_context field)
    highlights = Highlight.objects.filter(document__matter=matter).select_related(
        "document"
    )
    if since:
        highlights = highlights.filter(updated_at__gte=since)
    for hl in highlights:
        text_preview = hl.text[:500] if hl.text else ""
        if hl.text and len(hl.text) > 500:
            text_preview += "..."

        content = f'**Highlight [hl:{hl.id}]:** "{text_preview}" — {hl.citation}'
        if hl.slug:
            content = (
                f"**Highlight [hl:{hl.id}] ({hl.slug}):**"
                f' "{text_preview}" — {hl.citation}'
            )

        items.append(
            ContextItem(
                importance=hl.importance,
                item_type="highlight",
                content=content,
                source_id=hl.id,
            )
        )

    # Collect Facts (Timeline — always included)
    facts = Fact.objects.filter(matter=matter).prefetch_related(
        "documents", "highlights"
    )
    if since:
        facts = facts.filter(updated_at__gte=since)
    for fact in facts:
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

    # Collect Notes — only "always" items get full content here. "auto" notes
    # are chosen by the selector; "never" notes are excluded. Full content, no
    # truncation (parity with Documents).
    notes = Note.objects.filter(matter=matter).exclude(ai_context="never")
    if not include_auto:
        notes = notes.filter(ai_context="always")
    if since:
        notes = notes.filter(updated_at__gte=since)
    for note in notes:
        content_parts = [f"**Note [note:{note.id}]: {note.title}**"]
        if note.category:
            content_parts[0] += f" [{note.get_category_display()}]"
        if note.topic:
            content_parts[0] += f" - {note.topic}"
        if note.content:
            content_parts.append(note.content)

        items.append(
            ContextItem(
                importance=note.importance,
                item_type="note",
                content="\n".join(content_parts),
                source_id=note.id,
            )
        )

    # Collect firm-library notes pinned to "always" — the library's "auto"
    # notes go through the selector manifest instead (selector.build_manifest).
    if include_library_always:
        from apps.case.ai.selector import library_folder_path
        from apps.notes.models import get_library_notes

        library_always = get_library_notes().filter(ai_context="always")
        if since:
            library_always = library_always.filter(updated_at__gte=since)
        for note in library_always:
            if not note.content:
                continue
            folder_path = library_folder_path(note.folder)
            items.append(
                ContextItem(
                    importance=note.importance,
                    item_type="library",
                    content=(
                        f"**Library note [note:{note.id}]: {note.title}**"
                        f" ({folder_path})\n{note.content}"
                    ),
                    source_id=note.id,
                )
            )

    # Collect Case Law — only "always" items
    caselaw_qs = CaseLaw.objects.filter(matter=matter).exclude(ai_context="never")
    if not include_auto:
        caselaw_qs = caselaw_qs.filter(ai_context="always")
    if since:
        caselaw_qs = caselaw_qs.filter(updated_at__gte=since)
    for caselaw in caselaw_qs:
        content_parts = [f"**Case Law: {caselaw.case_name}**, {caselaw.citation}"]
        if caselaw.court:
            content_parts.append(f"Court: {caselaw.court}")
        if caselaw.date_filed:
            content_parts.append(f"Date: {caselaw.date_filed}")
        if caselaw.notes:
            content_parts.append(f"Notes: {caselaw.notes[:500]}")

        # Fetch full opinion text from CourtListener if available
        opinion_text = _fetch_caselaw_opinion_text(caselaw)
        if opinion_text:
            content_parts.append(f"Opinion:\n{opinion_text}")
        elif caselaw.summary:
            content_parts.append(f"Summary:\n{caselaw.summary}")

        items.append(
            ContextItem(
                importance=4,  # Default to HIGH for case law
                item_type="caselaw",
                content="\n".join(content_parts),
                source_id=caselaw.id,
            )
        )

    # Collect Emails (synced from Gmail) — grouped by thread, one item per
    # thread. Only "always" emails get full content here; "auto" threads are
    # chosen by the selector. With `since`, a thread is included when it has
    # new messages, rendering only those (older ones flagged as omitted) so
    # incremental auto-summaries see just the delta.
    # dedup: a message synced from two mailboxes contributes once.
    emails_qs = (
        Email.objects.filter(matter=matter)
        .dedup()
        .exclude(ai_context="never")
        .prefetch_related("attachment_files")
    )
    if not include_auto:
        emails_qs = emails_qs.filter(ai_context="always")
    for thread_emails in group_by_thread(emails_qs):
        shown = thread_emails
        if since:
            shown = [e for e in thread_emails if e.updated_at >= since]
            if not shown:
                continue
        items.append(
            ContextItem(
                importance=max(e.importance for e in shown),
                item_type="email",
                content=format_email_thread(
                    shown, omitted_earlier=len(thread_emails) - len(shown)
                ),
                source_id=min(e.id for e in thread_emails),
            )
        )

    # Collect Conversations with ai_context="always" (full content, HIGH importance)
    reference_convos = Conversation.objects.filter(
        matter=matter, ai_context="always"
    ).order_by("-updated_at")
    if since:
        reference_convos = reference_convos.filter(updated_at__gte=since)
    if current_conversation:
        reference_convos = reference_convos.exclude(id=current_conversation.id)

    for conv in reference_convos:
        content_parts = [
            f"**Reference Conversation: {conv.title or 'Untitled'}**",
            f"Date: {conv.updated_at.strftime('%b %d, %Y')}",
        ]

        # Include all messages from reference conversation
        messages = conv.messages.select_related("user").order_by("created_at")
        msg_lines = []

        for msg in messages:
            if msg.role == "user":
                user_name = msg.user.get_full_name() if msg.user else "User"
                msg_line = f"**{user_name}:** {msg.content}"
            else:
                msg_line = f"**Assistant:** {msg.content}"

            msg_lines.append(msg_line)

        if msg_lines:
            content_parts.append("\n".join(msg_lines))

        items.append(
            ContextItem(
                importance=4,  # HIGH importance for reference conversations
                item_type="conversation",
                content="\n".join(content_parts),
                source_id=conv.id,
            )
        )

    # Sort by importance (highest number = most important)
    items.sort(key=lambda x: x.importance, reverse=True)

    return items


def format_items_by_tier(items: list[ContextItem], tier: ImportanceTier) -> str:
    """Format all items of a specific importance tier."""
    tier_items = [item for item in items if item.tier == tier]

    if not tier_items:
        return "No items in this category."

    lines = [item.format() for item in tier_items]
    return "\n\n".join(lines)


REQUEST_INFO_TEMPLATE = """## Current Date

Today is {request_date}. Treat this as the current date when reasoning
about deadlines, elapsed time, or anything time-sensitive.

Messages in the conversation history are prefixed with a bracketed
date-time stamp (e.g. [Jul 04, 2026 02:15 PM]) showing when each was
sent, so you can follow the chronology. The stamps are metadata added by
the system. Never begin your own replies with one.

## Requesting Party

- Name: {user_name}
- Email: {user_email}
- Title: {role_title}
- Law Firm: {firm_name}

## Firm Team

Firm personnel and their titles. These are authoritative — when any of these
names appears in the matter record (time entries, notes, correspondence), use
the title listed here; do not infer anyone's role:

{team_lines}
"""


def build_request_info(user):
    """The Requesting Party + Firm Team sections of the system prompt.

    The roster anchors every firm name the model may meet in the matter
    record to an authoritative title, so it never guesses a colleague's
    role. Titles come from CustomUser.title, falling back to the attorney
    flag (see title_display)."""
    if not user:
        return ""
    company = Firm.objects.first()
    team_lines = "\n".join(
        f"- {u.full_name} — {u.title_display}"
        for u in CustomUser.objects.filter(is_active=True).order_by(
            "first_name", "username"
        )
    )
    return REQUEST_INFO_TEMPLATE.format(
        request_date=timezone.localdate().strftime("%A, %B %d, %Y"),
        user_name=user.get_full_name(),
        user_email=user.email,
        role_title=user.title_display,
        firm_name=company.name if company else "",
        team_lines=team_lines,
    )


def build_chat_history(conversation) -> list[dict]:
    """Provider-ready history for a conversation, shared by the case,
    intake, and agenda chats.

    Every message is prefixed with its sent date-time so the model can
    follow the chronology (REQUEST_INFO_TEMPLATE tells it the stamps are
    system metadata). When more than one person has participated, user
    messages also carry the sender's name.
    """
    messages = list(conversation.messages.select_related("user"))

    user_names = {
        (msg.user.get_full_name() or msg.user.username)
        for msg in messages
        if msg.role == "user" and msg.user
    }
    multi_user = len(user_names) > 1

    history = []
    for msg in messages:
        stamp = timezone.localtime(msg.created_at).strftime("%b %d, %Y %I:%M %p")
        content = msg.content
        if multi_user and msg.role == "user" and msg.user:
            name = msg.user.get_full_name() or msg.user.username
            content = f"[{name}]: {content}"
        history.append({"role": msg.role, "content": f"[{stamp}] {content}"})
    return history


# Conventions for citing matter sources in chat prose. Appended to the
# classic chat context in tasks.py alongside the write protocols; chat
# messages render as markdown, so the links are clickable.
SOURCE_LINKING = """CITING SOURCES. Documents and highlights in the context above carry
[doc:ID] and [hl:ID] handles next to their names. When your answer
draws on one, cite it inline as a markdown link:
- highlight: [Smith Dep. p.34](/case/highlights/88/link/) - the link
  opens the source document positioned at the highlight; use the
  highlight's citation as the link text.
- document: [Engagement Letter](/case/documents/17/view/) - only when
  no highlight covers the point.
Place each citation AFTER the sentence it supports: end the sentence
with its period, then the citation. ("The contract was signed on
March 3. [Smith Dep. p.34](/case/highlights/88/link/)")
Prefer the highlight whenever one supports the point. A highlight link
already identifies its document, so never add a second link to the
document itself for the same point. Documents and highlights are the
ONLY citable sources: never cite tasks, time entries, timeline facts,
events, notes, or other case records as authority for a point. Use
only ids whose handles appear in this context; never invent or guess
an id, and never write the raw [doc:ID], [hl:ID], or [note:ID] handles
in your reply."""

MATTER_CONTEXT_TEMPLATE = """
## Current Matter: {matter_name}

## Matter Overview
{matter_overview}

## Contacts & Parties
{contacts}

## Witnesses
{witnesses}

## Court Proceedings
{proceedings}

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

### Time Entries & Billing
{time_entries}

### Settlement Information
{settlement}
"""


def load_legal_prompt(jurisdiction: str = "") -> str:
    """
    Load the legal AI instructions from docs/ai-prompt.md.

    This file is read fresh on each call so edits take effect immediately.
    If *jurisdiction* is provided, ``[JURISDICTION]`` placeholders are replaced.
    """
    try:
        if LEGAL_PROMPT_FILE.exists():
            text = LEGAL_PROMPT_FILE.read_text(encoding="utf-8")
        else:
            logger.warning(f"Legal prompt file not found: {LEGAL_PROMPT_FILE}")
            return "You are a legal assistant. Be accurate and cite sources."
    except Exception as e:
        logger.error(f"Error reading legal prompt file: {e}")
        return "You are a legal assistant. Be accurate and cite sources."

    if jurisdiction:
        text = text.replace("[JURISDICTION]", jurisdiction)

    return text


def assemble_matter_context(matter, user=None, conversation=None) -> str:
    """
    Assemble context from all matter data, organized by importance.

    Args:
        matter: The Matter object to assemble context for
        user: The requesting user (for request info section)
        conversation: Optional Conversation object (excluded from reference conversations)

    Structure:
    1. Matter overview, contacts, proceedings (always included)
    2. Items organized by importance tier (CRITICAL, HIGH, MEDIUM, REFERENCE)
    3. Administrative info (tasks, events, settlement)
    """
    sections = {}

    # Matter Overview
    sections["matter_overview"] = format_matter_overview(matter)

    # Contacts
    sections["contacts"] = format_contacts(matter)

    # Witnesses
    sections["witnesses"] = format_witnesses(matter)

    # Proceedings
    sections["proceedings"] = format_proceedings(matter)

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

    # Time Entries
    sections["time_entries"] = format_time_entries(matter)

    # Settlement
    sections["settlement"] = format_settlement(matter)

    # Build the full system prompt
    company = Firm.objects.first()

    request_info = build_request_info(user)

    jurisdiction = (
        matter.jurisdiction
        or (company.jurisdiction if company else "")
        or "United States common law"
    )
    legal_prompt = load_legal_prompt(jurisdiction=jurisdiction)
    matter_context = MATTER_CONTEXT_TEMPLATE.format(matter_name=matter.name, **sections)

    return f"{request_info}{legal_prompt}\n\n---\n{matter_context}"


# How long a conversation may reuse its previously assembled context. Long
# enough to cover the quick follow-ups that dominate live chat ("now save
# that to a note"), short enough that a new line of questioning soon gets a
# fresh selector pass.
CONTEXT_REUSE_SECONDS = 600


def _context_fingerprint(matter, include_library, llm, user):
    """Cheap change marker for the matter's AI-visible material.

    Count + latest-updated_at per source table. Any write to the material
    the context is built from (including the AI's own note/fact/witness
    writes) changes the fingerprint and forces a rebuild, so reuse never
    hides a change. Sections that merely decorate the prompt (tasks,
    events, time entries) are deliberately not fingerprinted — staleness
    there is harmless within the TTL.
    """
    from apps.notes.models import get_library_notes

    querysets = {
        "doc": Document.objects.filter(matter=matter),
        "hl": Highlight.objects.filter(
            Q(document__matter=matter) | Q(caselaw__matter=matter)
        ),
        "fact": Fact.objects.filter(matter=matter),
        "note": Note.objects.filter(matter=matter),
        "case": CaseLaw.objects.filter(matter=matter),
        "wit": matter.witnesses.all(),
    }
    if include_library:
        querysets["lib"] = get_library_notes()

    parts = [llm, str(include_library), str(user.id if user else "")]
    for label, qs in querysets.items():
        agg = qs.aggregate(n=Count("id"), latest=Max("updated_at"))
        parts.append(f"{label}:{agg['n']}:{agg['latest']}")
    return "|".join(parts)


def assemble_matter_context_with_selection(
    matter, user_message, llm, user=None, conversation=None, include_library=True
) -> str:
    """
    Assemble context using intelligent selection for ai_context="auto" items.

    This is the primary context assembly function for AI chat. It:
    1. Builds fixed sections (overview, contacts, etc.) and "always" items
    2. Estimates remaining token budget
    3. Uses the selector to choose relevant "auto" items
    4. Assembles final context with selected items + "also available" list

    Args:
        matter: The Matter object
        user_message: The user's question (used by the selector)
        llm: The LLM key (for token budget)
        user: The requesting user
        conversation: Optional Conversation (excluded from reference conversations)
        include_library: Offer firm-library notes (standalone notes in
            AI-library folders) to the selector, and inject "always" library
            notes. The nightly auto-summary turns this off.
    """
    from .selector import (
        MODEL_CONTEXT_LIMITS,
        MODEL_HARD_LIMITS,
        build_manifest,
        estimate_tokens,
        select_context,
    )

    # Quick follow-ups reuse the context assembled for the previous turn
    # (skipping the expensive Flash selection) as long as nothing the
    # context is built from has changed. A stable context also keeps the
    # provider-side prompt caches warm between turns.
    ctx_cache_key = f"ai_ctx_{conversation.id}" if conversation else None
    fingerprint = None
    if ctx_cache_key:
        fingerprint = _context_fingerprint(matter, include_library, llm, user)
        entry = cache.get(ctx_cache_key)
        if entry and entry.get("fingerprint") == fingerprint:
            logger.info(
                "Reusing assembled context for conversation %s", conversation.id
            )
            return entry["context"]

    # Build the fixed sections (same as assemble_matter_context)
    sections = {}
    sections["matter_overview"] = format_matter_overview(matter)
    sections["contacts"] = format_contacts(matter)
    sections["witnesses"] = format_witnesses(matter)
    sections["proceedings"] = format_proceedings(matter)

    sections["tasks"] = format_tasks(matter)
    sections["events"] = format_events(matter)
    sections["time_entries"] = format_time_entries(matter)
    sections["settlement"] = format_settlement(matter)

    # Collect "always" items (Documents/CaseLaw with ai_context="always",
    # plus all Highlights, Facts, Notes, Conversations)
    always_items = collect_context_items(
        matter,
        current_conversation=conversation,
        include_library_always=include_library,
    )

    # Build request info and legal prompt
    company = Firm.objects.first()
    request_info = build_request_info(user)

    jurisdiction = (
        matter.jurisdiction
        or (company.jurisdiction if company else "")
        or "United States common law"
    )
    legal_prompt = load_legal_prompt(jurisdiction=jurisdiction)

    # Format always items by tier
    always_critical = format_items_by_tier(always_items, ImportanceTier.CRITICAL)
    always_high = format_items_by_tier(always_items, ImportanceTier.HIGH)
    always_medium = format_items_by_tier(always_items, ImportanceTier.MEDIUM)
    always_reference = format_items_by_tier(always_items, ImportanceTier.REFERENCE)

    # Estimate tokens used by fixed content so far
    fixed_content = (
        request_info
        + legal_prompt
        + sections["matter_overview"]
        + sections["contacts"]
        + sections["witnesses"]
        + sections["proceedings"]
        + always_critical
        + always_high
        + always_medium
        + always_reference
        + sections["tasks"]
        + sections["events"]
        + sections["time_entries"]
        + sections["settlement"]
    )
    fixed_tokens = estimate_tokens(fixed_content)

    # Calculate remaining budget for auto items
    total_budget = MODEL_CONTEXT_LIMITS.get(llm, 150_000)
    # Reserve 10K for conversation history + response
    remaining_budget = total_budget - fixed_tokens - 10_000

    # Build manifest and run selector for "auto" items
    manifest_items, content_map = build_manifest(
        matter, current_conversation=conversation, include_library=include_library
    )

    selected_contents = []
    unselected_items = []
    if manifest_items and remaining_budget > 0:
        selected_contents, unselected_items = select_context(
            manifest_items, content_map, user_message, remaining_budget
        )

    # Build the selected items section
    selected_section = ""
    if selected_contents:
        selected_section = (
            "\n\n## Selected Materials\n"
            "The following materials were selected as relevant to your question:\n\n"
            + "\n\n".join(selected_contents)
        )

    # Build "also available" section for non-selected auto items
    also_available = ""
    if unselected_items:
        lines = [
            "\n\n## Also Available (not included in this context)",
            "The following materials exist but were not included. "
            "Ask to see specific items if needed:",
        ]
        for item in unselected_items:
            date_str = f", {item.date}" if item.date else ""
            lines.append(
                f'- {item.item_type.title()}: "{item.name}" ({item.category}{date_str})'
            )
        also_available = "\n".join(lines)

    # Assemble full context
    matter_context = MATTER_CONTEXT_TEMPLATE.format(
        matter_name=matter.name,
        critical_items=always_critical,
        high_items=always_high,
        medium_items=always_medium,
        reference_items=always_reference,
        **{
            k: v
            for k, v in sections.items()
            if k
            not in ("critical_items", "high_items", "medium_items", "reference_items")
        },
    )

    # Hard-ceiling enforcement. The selector caps its own auto-selected slice
    # against MODEL_CONTEXT_LIMITS, but the always-included content (fixed
    # sections + ai_context="always" items + every Highlight / Fact / Note /
    # reference Conversation) isn't trimmed by the selector and can push the
    # final prompt past the model's window. If that happens, demote all
    # auto-selected items to "Also Available" so the AI still knows they exist
    # and can ask the user, instead of letting Anthropic / Google reject the
    # request with a "prompt too long" error.
    hard_limit = MODEL_HARD_LIMITS.get(llm, 1_000_000)
    # 80% of the window so the chat history (added at send time) plus any
    # under-counting in estimate_tokens (chars/4) still leaves room. The
    # send-site guard in tasks.py is the final defense.
    safe_ceiling = int(hard_limit * 0.80)
    provisional = (
        f"{request_info}{legal_prompt}\n\n---\n{matter_context}"
        f"{selected_section}{also_available}"
    )
    if estimate_tokens(provisional) > safe_ceiling and selected_contents:
        logger.warning(
            "Assembled context (~%d tokens) exceeds safe ceiling for %s (%d); "
            "demoting %d auto-selected items to 'Also Available'.",
            estimate_tokens(provisional),
            llm,
            safe_ceiling,
            len(selected_contents),
        )
        # Move every manifest item into the "Also Available" listing so the
        # AI can name them in a follow-up question.
        selected_section = ""
        if manifest_items:
            lines = [
                "\n\n## Also Available (not included in this context)",
                "The following materials exist but were omitted to keep the "
                "prompt within the model's context window. Ask to see specific "
                "items if needed:",
            ]
            for item in manifest_items:
                date_str = f", {item.date}" if item.date else ""
                lines.append(
                    f'- {item.item_type.title()}: "{item.name}" '
                    f"({item.category}{date_str})"
                )
            also_available = "\n".join(lines)

    assembled = (
        f"{request_info}{legal_prompt}\n\n---\n{matter_context}"
        f"{selected_section}{also_available}"
    )
    if ctx_cache_key:
        cache.set(
            ctx_cache_key,
            {"context": assembled, "fingerprint": fingerprint},
            timeout=CONTEXT_REUSE_SECONDS,
        )
    return assembled


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


def format_witnesses(matter) -> str:
    """Format the witness list."""
    witnesses = matter.witnesses.all()

    if not witnesses:
        return "No witnesses recorded."

    lines = []
    for witness in witnesses:
        line = (
            f"- {witness.name} ({witness.get_alignment_display()},"
            f" importance {witness.importance})"
        )
        if witness.affiliation:
            line += f" - {witness.affiliation}"
        if witness.knowledge:
            line += f"\n  Knows: {witness.knowledge[:300]}"
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
        "date_completed", "importance", "date_due"
    )[:20]

    if not tasks:
        return "No tasks."

    lines = []
    for task in tasks:
        status_icon = "[DONE]" if task.date_completed else "[PENDING]"
        line = f"- {status_icon} P{task.importance}: {task.description}"
        if task.date_due:
            line += f" (Due: {task.date_due})"
        lines.append(line)

    return "\n".join(lines)


def format_events(matter) -> str:
    """Format events, upcoming first."""
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


def format_time_entries(matter) -> str:
    """Format time entries with invoice relationships."""
    entries = (
        TimeEntry.objects.filter(matter=matter)
        .select_related("user", "invoice")
        .order_by("-date")
    )

    if not entries:
        return "No time entries."

    lines = []
    for entry in entries:
        user_name = entry.user.get_full_name() if entry.user else "Unknown"
        fee = entry.hours * entry.rate if entry.rate else 0
        line = f"- [{entry.date}] {entry.actions} — {entry.hours}h @ ${entry.rate}/hr (${fee:,.2f})"
        line += f" by {user_name}"
        if entry.comp:
            line += " [COMP]"
        if entry.invoice:
            line += f" [Invoice #{entry.invoice.id}, {entry.invoice.status}]"
        lines.append(line)

    return "\n".join(lines)


def format_invoice(invoice) -> str:
    """Format a single invoice with totals, balance, and metadata."""
    from apps.activity.expenses.models import ExpenseEntry
    from apps.activity.flat_fees.models import FlatFeeEntry
    from apps.activity.time.models import TimeEntry

    value = invoice.value
    lines = [
        f"**Invoice #{invoice.id}** — {invoice.status_display}",
        f"Period covered: through {invoice.date_limit}",
        f"Date issued: {invoice.date_issued}",
    ]

    lines.append(
        f"Fees: ${value['net_fees']:,.2f} (gross ${value['gross_fees']:,.2f}, "
        f"comp ${value['comp_fees']:,.2f})"
    )
    lines.append(
        f"Expenses: ${value['net_expenses']:,.2f} (gross ${value['gross_expenses']:,.2f}, "
        f"comp ${value['comp_expenses']:,.2f})"
    )
    lines.append(
        f"Flat fees: ${value['net_flat_fees']:,.2f} (gross ${value['gross_flat_fees']:,.2f}, "
        f"comp ${value['comp_flat_fees']:,.2f})"
    )
    if invoice.discount:
        lines.append(f"Discount: ${invoice.discount:,.2f}")
    lines.append(f"Total: ${value['final_total']:,.2f}")
    lines.append(f"Balance remaining: ${invoice.amount_remaining:,.2f}")

    time_count = TimeEntry.objects.filter(invoice=invoice).count()
    expense_count = ExpenseEntry.objects.filter(invoice=invoice).count()
    flat_count = FlatFeeEntry.objects.filter(invoice=invoice).count()
    lines.append(
        f"Line items: {time_count} time, {expense_count} expense, {flat_count} flat fee"
    )

    if invoice.message:
        lines.append(f"Message: {invoice.message}")
    if invoice.comment:
        lines.append(f"Comment: {invoice.comment}")

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
