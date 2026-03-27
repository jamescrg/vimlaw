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

from .gemini_client import send_to_gemini
from .models import Conversation

logger = logging.getLogger(__name__)

# Usable context budget per model (roughly 75% of full context window,
# reserving space for conversation history and response).
MODEL_CONTEXT_LIMITS = {
    "claude": 150_000,
    "claude-opus": 150_000,
    "gemini-flash": 750_000,
    "gemini-pro": 750_000,
    "gemini-pro-latest": 750_000,
}

# If total auto content is under this many words, include everything
# without calling the selector (saves an API call on small matters).
SMALL_MATTER_THRESHOLD = 30_000

SELECTOR_SYSTEM_PROMPT = """\
You are a context selector for a legal AI assistant. Given a user's question \
and a manifest of available case materials, select which materials should be \
included in context to answer the question effectively.

Return ONLY a JSON object with this format:
{"selected": [{"type": "document", "id": 123}, {"type": "caselaw", "id": 45}, {"type": "conversation", "id": 67}]}

Rules:
- Select materials that are relevant to the user's question.
- Stay within the token budget specified below.
- Prioritize higher-priority items when budget is tight.
- When in doubt about relevance, include rather than exclude.
- Return ONLY the JSON object, no other text."""


@dataclass
class ManifestItem:
    """A lightweight description of a material for the selector."""

    item_type: str  # "document", "caselaw", or "conversation"
    item_id: int
    name: str
    category: str
    date: str | None
    description: str
    word_count: int
    importance: int


def estimate_tokens(text: str) -> int:
    """Estimate token count from text (1 token ~= 4 characters)."""
    return len(text) // 4


def build_manifest(matter, current_conversation=None):
    """
    Build a lightweight manifest of all ai_context="auto" items.

    Returns:
        tuple: (manifest_items, content_map)
            - manifest_items: list of ManifestItem for the selector
            - content_map: dict mapping (type, id) to full content string
    """
    manifest_items = []
    content_map = {}

    # Documents with ai_context="auto"
    for doc in Document.objects.filter(matter=matter, ai_context="auto"):
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
            )
        )

        # Build full content for this document (same format as context.py)
        content_parts = [f"**Document: {doc.name}** ({doc.category})"]
        if doc.date:
            content_parts[0] += f" - {doc.date}"
        if doc.description:
            content_parts.append(f"Description: {doc.description}")
        content_parts.append(f"Content:\n{doc.ocr_text}")
        content_map[("document", doc.id)] = "\n".join(content_parts)

    # Case law with ai_context="auto"
    for caselaw in CaseLaw.objects.filter(matter=matter, ai_context="auto"):
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

    return manifest_items, content_map


def format_manifest_for_prompt(items: list[ManifestItem], token_budget: int) -> str:
    """Format manifest items into a compact text list for the selector prompt."""
    lines = [f"TOKEN BUDGET: ~{token_budget:,} tokens available for materials.\n"]

    for item in items:
        type_label = {"document": "DOC", "caselaw": "CASE", "conversation": "CONV"}.get(
            item.item_type, item.item_type.upper()
        )
        date_str = f", {item.date}" if item.date else ""
        lines.append(
            f'[{type_label}-{item.item_id}] "{item.name}" '
            f"({item.category}{date_str}) - {item.description} "
            f"[~{item.word_count:,} words, priority: {item.importance}/5]"
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

    # Check if everything fits — skip selector API call
    total_words = sum(item.word_count for item in manifest_items)
    if total_words <= SMALL_MATTER_THRESHOLD:
        logger.info(
            "Small matter (%d words across %d auto items) — including all",
            total_words,
            len(manifest_items),
        )
        all_contents = []
        for item in manifest_items:
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
    selected = data.get("selected", [])

    keys = []
    for item in selected:
        item_type = item.get("type", "")
        item_id = item.get("id")
        if item_type in ("document", "caselaw", "conversation") and item_id is not None:
            keys.append((item_type, int(item_id)))

    return keys


def _resolve_content(key: tuple[str, int], content_map: dict) -> str:
    """Resolve content for a manifest item, fetching from CourtListener if needed."""
    value = content_map.get(key)
    if value is None:
        return ""
    if isinstance(value, str):
        return value

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
    """Fallback: select items by importance until budget is filled."""
    sorted_items = sorted(manifest_items, key=lambda x: x.importance, reverse=True)
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
