"""
Intelligent context selection for AI chat.

Builds a lightweight manifest of available materials and uses Gemini Flash
to select which ones are relevant to the user's question, staying within
the token budget for the chosen model.
"""

import json
import logging
from dataclasses import dataclass

from apps.case.models import CaseLaw, Document
from apps.invoicing.invoices.models import Invoice
from apps.mail.ai import (
    format_email_thread,
    group_by_thread,
    thread_subject,
    thread_word_count,
)
from apps.mail.models import Email
from apps.notes.models import Note, get_library_notes

from .gemini_client import send_to_gemini
from .models import Conversation

logger = logging.getLogger(__name__)

# Usable context budget per model — the per-request soft cap the SELECTOR
# uses when deciding how much auto-content to include. Sized at roughly
# 60% of each model's window, leaving ~40% headroom for the fixed sections
# (overview / contacts / proceedings / always-included highlights / facts /
# notes / reference conversations / etc.) which the selector does not trim.
# Without that headroom, heavy matters can push the assembled prompt past
# the model's window even though the selector itself stayed under budget.
# Every Claude and Gemini model in the picker has a ~1M-token window.
MODEL_CONTEXT_LIMITS = {
    "claude": 600_000,
    "claude-opus-5": 600_000,
    "claude-fable": 600_000,
    "claude-opus": 600_000,
    "claude-opus-4-6": 600_000,
    "gemini-flash": 750_000,
    "gemini-pro": 750_000,
    "gemini-pro-latest": 750_000,
}

# Hard ceilings (the actual model context windows). Used by context
# assembly as a final safety check — if the assembled prompt would exceed
# the ceiling, auto-selected items are dropped to fit before sending.
MODEL_HARD_LIMITS = {
    "claude": 1_000_000,
    "claude-opus-5": 1_000_000,
    "claude-fable": 1_000_000,
    "claude-opus": 1_000_000,
    "claude-opus-4-6": 1_000_000,
    "gemini-flash": 1_000_000,
    "gemini-pro": 1_000_000,
    "gemini-pro-latest": 1_000_000,
}

# If total auto content is under this many words, include everything
# without calling the selector (saves an API call on small matters).
SMALL_MATTER_THRESHOLD = 30_000

SELECTOR_SYSTEM_PROMPT = """\
You are a context selector for a legal AI assistant. Given a user's question \
and a manifest of available case materials, select which materials should be \
included in context to answer the question effectively.

Return ONLY a JSON object with this format:
{"selected": [{"type": "document", "id": 123}, {"type": "note", "id": 89}, {"type": "caselaw", "id": 45}, {"type": "conversation", "id": 67}, {"type": "email", "id": 12}, {"type": "invoice", "id": 42}, {"type": "library", "id": 7}]}

Rules:
- Select materials that are relevant to the user's question.
- Stay within the token budget specified below.
- Prioritize higher-priority items when budget is tight.
- When in doubt about relevance, include rather than exclude.
- Invoices are billing/financial records — only include them if the user is \
asking about billing, fees, payments, balances, or specific invoices.
- Library items are firm-wide reference notes (research outlines and practice \
guides), not case materials. Include one only when its topic clearly bears on \
the legal question being asked, and select at most 5 library items.
- Return ONLY the JSON object, no other text."""


@dataclass
class ManifestItem:
    """A lightweight description of a material for the selector."""

    item_type: str  # "document", "caselaw", "conversation", "note", "email", "invoice", "library"
    item_id: int
    name: str
    category: str
    date: str | None
    description: str
    word_count: int
    importance: int
    # Agent index extras (build_manifest(include_always=True)): the read
    # handle the tools take, whether the attorney pinned the item
    # (ai_context="always"), and its size in characters.
    handle: str = ""
    pinned: bool = False
    size_chars: int = 0


# Characters per token for the size estimate. The folk figure is 4, and
# that is what this used to be; measured against count_tokens on this
# firm's actual material it under-counts badly. Opus 4.8 on the six
# largest OCR'd documents on dev (2026-08-20): 2.23 chars/token overall,
# worst 1.56; a full matter context: 2.29; plain prose: ~3. The Opus 4.7+
# tokenizer is also up to ~1.35x denser than Sonnet/Opus 4.6. A prompt
# that estimated under 800K at chars/4 was rejected by Anthropic at 1.14M
# tokens. 2.5 keeps the estimate within the guards' 20% margin on
# measured content; the Claude send path additionally verifies large
# prompts with an exact count.
CHARS_PER_TOKEN = 2.5


def estimate_tokens(text: str) -> int:
    """Estimate token count from text (conservative: 1 token ~= 2.5 chars)."""
    return int(len(text) / CHARS_PER_TOKEN)


def library_folder_path(folder):
    """Human-readable folder path for a library note, e.g. "Research/Evidence"."""
    if folder is None:
        return ""
    return "/".join(f.name for f in folder.get_ancestors() + [folder])


def build_manifest(
    matter, current_conversation=None, include_library=True, include_always=False
):
    """
    Build a lightweight manifest of all ai_context="auto" items.

    With ``include_always`` the "always" documents, cases and emails are
    listed too (flagged ``pinned``): the agent turn's material index covers
    everything the model may read, since nothing is preloaded there.

    Returns:
        tuple: (manifest_items, content_map)
            - manifest_items: list of ManifestItem for the selector
            - content_map: dict mapping (type, id) to full content string
    """
    manifest_items = []
    content_map = {}
    listed = ("auto", "always") if include_always else ("auto",)

    # Documents with ai_context="auto"
    for doc in Document.objects.filter(matter=matter, ai_context__in=listed):
        if not doc.ocr_text or doc.ocr_status not in ("completed", "extracted"):
            continue

        # Best available description for the manifest
        if doc.summary:
            desc = doc.summary
        elif doc.description:
            desc = doc.description
        else:
            desc = doc.ocr_text[:200].strip()
            if len(doc.ocr_text) > 200:
                desc += "..."

        word_count = len(doc.ocr_text.split())

        manifest_items.append(
            ManifestItem(
                item_type="document",
                item_id=doc.id,
                name=doc.name,
                category=doc.category,
                date=str(doc.date) if doc.date else None,
                description=desc,
                word_count=word_count,
                importance=doc.importance,
                handle=f"doc:{doc.id}",
                pinned=doc.ai_context == "always",
                size_chars=len(doc.ocr_text),
            )
        )

        # Build full content for this document (same format as context.py)
        content_parts = [f"**Document [doc:{doc.id}]: {doc.name}** ({doc.category})"]
        if doc.date:
            content_parts[0] += f" - {doc.date}"
        if doc.description:
            content_parts.append(f"Description: {doc.description}")
        content_parts.append(f"Content:\n{doc.ocr_text}")
        content_map[("document", doc.id)] = "\n".join(content_parts)

    # Notes (all of the matter's notes — notes carry no AI knobs)
    for note in Note.objects.filter(matter=matter):
        content_text = note.content or ""
        if not content_text.strip():
            continue

        desc = content_text[:200].strip()
        if len(content_text) > 200:
            desc += "..."

        category = note.get_category_display()
        if note.topic:
            category += f" — {note.topic}"

        manifest_items.append(
            ManifestItem(
                item_type="note",
                item_id=note.id,
                name=note.title,
                category=category,
                date=str(note.updated_at.date()) if note.updated_at else None,
                description=desc,
                word_count=len(content_text.split()),
                importance=note.importance,
                handle=f"note:{note.id}",
                size_chars=len(content_text),
            )
        )

        # Full note content (no truncation) — same shape as collect_context_items
        content_parts = [f"**Note [note:{note.id}]: {note.title}**"]
        if note.category:
            content_parts[0] += f" [{note.get_category_display()}]"
        if note.topic:
            content_parts[0] += f" - {note.topic}"
        content_parts.append(content_text)
        content_map[("note", note.id)] = "\n".join(content_parts)

    # Case law with ai_context="auto"
    for caselaw in CaseLaw.objects.filter(matter=matter, ai_context__in=listed):
        if caselaw.notes:
            desc = caselaw.notes[:200]
        elif caselaw.summary:
            desc = caselaw.summary[:200].strip()
            if len(caselaw.summary) > 200:
                desc += "..."
        else:
            desc = ""

        manifest_items.append(
            ManifestItem(
                item_type="caselaw",
                item_id=caselaw.id,
                name=f"{caselaw.case_name}, {caselaw.citation}",
                category=caselaw.court or "",
                date=str(caselaw.date_filed) if caselaw.date_filed else None,
                description=desc,
                word_count=0,
                importance=caselaw.importance,
                handle=f"case:{caselaw.id}",
                pinned=caselaw.ai_context == "always",
                size_chars=len(caselaw.summary or "") + len(caselaw.notes or ""),
            )
        )

        # Content fetched on demand after selection — store caselaw obj for now
        content_map[("caselaw", caselaw.id)] = caselaw  # Resolved lazily

    # Conversations with ai_context="auto"
    auto_convos = Conversation.objects.filter(matter=matter, ai_context="auto")
    if current_conversation:
        auto_convos = auto_convos.exclude(id=current_conversation.id)

    for conv in auto_convos:
        messages = conv.messages.select_related("user").order_by("created_at")
        msg_count = messages.count()
        if msg_count == 0:
            continue

        # Best available description
        desc = conv.summary or conv.title or "Untitled conversation"

        # Participant names
        participants = conv.get_participants()
        participant_names = ", ".join(u.get_full_name() for u in participants[:3])

        # Date range
        first_msg = messages.first()
        last_msg = messages.order_by("-created_at").first()
        date_str = (
            f"{first_msg.created_at.strftime('%Y-%m-%d')} to "
            f"{last_msg.created_at.strftime('%Y-%m-%d')}"
        )

        # Word count
        total_words = sum(len(m.content.split()) for m in messages)

        manifest_items.append(
            ManifestItem(
                item_type="conversation",
                item_id=conv.id,
                name=conv.title or "Untitled",
                category=f"{msg_count} messages, {participant_names}",
                date=date_str,
                description=desc,
                word_count=total_words,
                importance=3,
                handle=f"conv:{conv.id}",
                size_chars=sum(len(m.content) for m in messages),
            )
        )

        # Build full content
        content_parts = [
            f"**Conversation: {conv.title or 'Untitled'}**",
            f"Date: {conv.updated_at.strftime('%b %d, %Y')}",
            f"Participants: {participant_names}",
        ]
        msg_lines = []
        for msg in messages:
            if msg.role == "user":
                user_name = msg.user.get_full_name() if msg.user else "User"
                msg_lines.append(f"**{user_name}:** {msg.content}")
            else:
                msg_lines.append(f"**Assistant:** {msg.content}")
        if msg_lines:
            content_parts.append("\n".join(msg_lines))
        content_map[("conversation", conv.id)] = "\n".join(content_parts)

    # Emails with ai_context="auto" — one manifest item per Gmail thread (a
    # long thread as N entries would bloat the manifest, and the thread is
    # the unit the attorney thinks in). item_id is the lowest Email id in
    # the thread, a stable integer key.
    # dedup: a message synced from two mailboxes appears once.
    auto_emails = (
        Email.objects.filter(matter=matter, ai_context__in=listed)
        .dedup()
        .prefetch_related("attachment_files")
    )
    for thread_emails in group_by_thread(auto_emails):
        first, last = thread_emails[0], thread_emails[-1]
        item_id = min(e.id for e in thread_emails)
        total_words = thread_word_count(thread_emails)

        first_date = first.date.strftime("%Y-%m-%d") if first.date else None
        last_date = last.date.strftime("%Y-%m-%d") if last.date else None
        if first_date and last_date and first_date != last_date:
            date_str = f"{first_date} to {last_date}"
        else:
            date_str = last_date or first_date

        manifest_items.append(
            ManifestItem(
                item_type="email",
                item_id=item_id,
                name=thread_subject(thread_emails),
                category=(
                    f"Email thread, {len(thread_emails)} "
                    f"message{'s' if len(thread_emails) != 1 else ''}"
                ),
                date=date_str,
                description=first.snippet or first.body_text[:200].strip(),
                word_count=total_words,
                importance=max(e.importance for e in thread_emails),
                handle=f"thread:{first.thread_id or first.gmail_id}",
                pinned=any(e.ai_context == "always" for e in thread_emails),
                size_chars=sum(len(e.body_text or "") for e in thread_emails),
            )
        )
        content_map[("email", item_id)] = format_email_thread(thread_emails)

    # Invoices — every invoice on the matter is offered to the selector, but
    # only included when the user's question is actually about billing.
    for invoice in Invoice.objects.filter(matter=matter).order_by("-date_issued"):
        manifest_items.append(
            ManifestItem(
                item_type="invoice",
                item_id=invoice.id,
                name=f"Invoice #{invoice.id}",
                category=invoice.status,
                date=str(invoice.date_issued) if invoice.date_issued else None,
                description=(
                    f"Period through {invoice.date_limit}, "
                    f"balance ${invoice.amount_remaining:,.2f}"
                ),
                word_count=200,  # rough estimate; resolved on demand
                importance=1,
                handle=f"inv:{invoice.id}",
            )
        )
        # Resolved lazily via _resolve_content to avoid extra aggregation
        # queries for invoices the selector ends up not picking.
        content_map[("invoice", invoice.id)] = invoice

    # Firm library — every standalone note. Offered on every matter; the
    # selector includes one only when its topic bears on the question.
    if include_library:
        library_notes = get_library_notes().select_related(
            "folder",
            "folder__parent",
            "folder__parent__parent",
            "folder__parent__parent__parent",
        )
        for note in library_notes:
            content_text = note.content or ""
            if not content_text.strip():
                continue

            desc = note.summary or content_text[:200].strip()
            if not note.summary and len(content_text) > 200:
                desc += "..."

            folder_path = library_folder_path(note.folder)

            manifest_items.append(
                ManifestItem(
                    item_type="library",
                    item_id=note.id,
                    name=note.title,
                    category=f"Library: {folder_path}",
                    date=str(note.updated_at.date()) if note.updated_at else None,
                    description=desc,
                    word_count=len(content_text.split()),
                    importance=note.importance,
                    handle=f"lib:{note.id}",
                    size_chars=len(content_text),
                )
            )
            content_map[("library", note.id)] = (
                f"**Library note [note:{note.id}]: {note.title}**"
                f" ({folder_path})\n{content_text}"
            )

    return manifest_items, content_map


def format_manifest_for_prompt(items: list[ManifestItem], token_budget: int) -> str:
    """Format manifest items into a compact text list for the selector prompt."""
    lines = [f"TOKEN BUDGET: ~{token_budget:,} tokens available for materials.\n"]

    for item in items:
        type_label = {
            "document": "DOC",
            "caselaw": "CASE",
            "conversation": "CONV",
            "note": "NOTE",
            "email": "EMAIL",
            "library": "LIB",
        }.get(item.item_type, item.item_type.upper())
        date_str = f", {item.date}" if item.date else ""
        lines.append(
            f'[{type_label}-{item.item_id}] "{item.name}" '
            f"({item.category}{date_str}) - {item.description} "
            f"[~{item.word_count:,} words, importance: {item.importance}/7]"
        )

    return "\n".join(lines)


def select_context(
    manifest_items: list[ManifestItem],
    content_map: dict,
    user_message: str,
    token_budget: int,
) -> tuple[list[str], list[ManifestItem]]:
    """
    Use Gemini Flash to select which materials are relevant to the question.

    Args:
        manifest_items: Lightweight descriptions of available materials
        content_map: Maps (type, id) to full content strings
        user_message: The user's question
        token_budget: Available token budget for materials

    Returns:
        tuple: (selected_contents, unselected_items)
            - selected_contents: list of full content strings for selected items
            - unselected_items: manifest items that were not selected
    """
    if not manifest_items:
        return [], []

    # Check if everything fits — skip selector API call. Invoices are never
    # auto-included even on small matters: they're financial records that
    # should only enter context when the user's question is about billing.
    # Library items likewise never ride the short-circuit: the firm library
    # is matter-independent bulk that must always pass relevance selection.
    matter_items = [
        i for i in manifest_items if i.item_type not in ("invoice", "library")
    ]
    invoice_items = [i for i in manifest_items if i.item_type == "invoice"]
    library_items = [i for i in manifest_items if i.item_type == "library"]
    total_words = sum(item.word_count for item in matter_items)
    if (
        total_words <= SMALL_MATTER_THRESHOLD
        and not invoice_items
        and not library_items
    ):
        logger.info(
            "Small matter (%d words across %d auto items) — including all",
            total_words,
            len(manifest_items),
        )
        all_contents = []
        for item in matter_items:
            key = (item.item_type, item.item_id)
            if key in content_map:
                content = _resolve_content(key, content_map)
                if content:
                    all_contents.append(content)
        return all_contents, []

    # Call Gemini Flash for intelligent selection
    manifest_text = format_manifest_for_prompt(manifest_items, token_budget)
    prompt = f"USER'S QUESTION: {user_message}\n\nAVAILABLE MATERIALS:\n{manifest_text}"

    try:
        response_text, _, _ = send_to_gemini(
            system_context=SELECTOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            model="gemini-2.5-flash",
        )

        selected_keys = _parse_selector_response(response_text)

    except Exception as e:
        logger.warning("Context selector failed, falling back to importance: %s", e)
        selected_keys = _fallback_by_importance(
            manifest_items, content_map, token_budget
        )

    # Build results — resolve caselaw content on demand
    selected_contents = []
    selected_key_set = set(selected_keys)
    unselected_items = []

    for item in manifest_items:
        key = (item.item_type, item.item_id)
        if key in selected_key_set and key in content_map:
            content = _resolve_content(key, content_map)
            if content:
                selected_contents.append(content)
        else:
            unselected_items.append(item)

    logger.info(
        "Context selector: %d selected, %d unselected out of %d auto items",
        len(selected_contents),
        len(unselected_items),
        len(manifest_items),
    )

    return selected_contents, unselected_items


def _parse_selector_response(response_text: str) -> list[tuple[str, int]]:
    """Parse the JSON response from the selector model."""
    # Strip markdown code fences if present
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (fences)
        lines = [line for line in lines if not line.strip().startswith("```")]
        text = "\n".join(lines)

    data = json.loads(text)
    selected = data.get("selected") or []

    keys = []
    for item in selected:
        item_type = item.get("type", "")
        item_id = item.get("id")
        if (
            item_type
            in (
                "document",
                "caselaw",
                "conversation",
                "invoice",
                "note",
                "email",
                "library",
            )
            and item_id is not None
        ):
            keys.append((item_type, int(item_id)))

    return keys


def _resolve_content(key: tuple[str, int], content_map: dict) -> str:
    """Resolve content for a manifest item, fetching from CourtListener if needed."""
    value = content_map.get(key)
    if value is None:
        return ""
    if isinstance(value, str):
        return value

    # Invoice object — format on demand
    if isinstance(value, Invoice):
        from apps.case.ai.context import format_invoice

        resolved = format_invoice(value)
        content_map[key] = resolved
        return resolved

    # CaseLaw object — fetch full text on demand
    caselaw = value
    from apps.case.ai.context import _fetch_caselaw_opinion_text

    content_parts = [f"**Case Law: {caselaw.case_name}**, {caselaw.citation}"]
    if caselaw.court:
        content_parts.append(f"Court: {caselaw.court}")
    if caselaw.date_filed:
        content_parts.append(f"Date: {caselaw.date_filed}")
    if caselaw.notes:
        content_parts.append(f"Notes: {caselaw.notes[:500]}")

    opinion_text = _fetch_caselaw_opinion_text(caselaw)
    if opinion_text:
        content_parts.append(f"Opinion:\n{opinion_text}")
    elif caselaw.summary:
        content_parts.append(f"Summary:\n{caselaw.summary}")

    resolved = "\n".join(content_parts)
    content_map[key] = resolved  # Cache for reuse
    return resolved


def _fallback_by_importance(
    manifest_items: list[ManifestItem],
    content_map: dict,
    token_budget: int,
) -> list[tuple[str, int]]:
    """Fallback: select items by importance until budget is filled.

    Invoices and library items are skipped — invoices are explicit-only, and
    the firm library is question-blind bulk that would flood a matter chat if
    importance-ranked in when the selector model fails.
    """
    eligible = [
        item for item in manifest_items if item.item_type not in ("invoice", "library")
    ]
    sorted_items = sorted(eligible, key=lambda x: x.importance, reverse=True)
    selected = []
    used_tokens = 0

    for item in sorted_items:
        key = (item.item_type, item.item_id)
        content = _resolve_content(key, content_map)
        item_tokens = estimate_tokens(content)

        if used_tokens + item_tokens > token_budget:
            continue

        selected.append(key)
        used_tokens += item_tokens

    return selected
