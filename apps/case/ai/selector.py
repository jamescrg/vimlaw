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
{"selected": [{"type": "document", "id": 123}, {"type": "caselaw", "id": 45}]}

Rules:
- Select materials that are relevant to the user's question.
- Stay within the token budget specified below.
- Prioritize higher-priority items when budget is tight.
- When in doubt about relevance, include rather than exclude.
- Return ONLY the JSON object, no other text."""


@dataclass
class ManifestItem:
    """A lightweight description of a material for the selector."""

    item_type: str  # "document" or "caselaw"
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
        elif caselaw.text:
            desc = caselaw.text[:200].strip()
            if len(caselaw.text) > 200:
                desc += "..."
        else:
            desc = ""

        word_count = len(caselaw.text.split()) if caselaw.text else 0

        manifest_items.append(
            ManifestItem(
                item_type="caselaw",
                item_id=caselaw.id,
                name=f"{caselaw.case_name}, {caselaw.citation}",
                category=caselaw.court or "",
                date=str(caselaw.date_filed) if caselaw.date_filed else None,
                description=desc,
                word_count=word_count,
                importance=caselaw.importance,
            )
        )

        # Build full content
        content_parts = [f"**Case Law: {caselaw.case_name}**, {caselaw.citation}"]
        if caselaw.court:
            content_parts.append(f"Court: {caselaw.court}")
        if caselaw.date_filed:
            content_parts.append(f"Date: {caselaw.date_filed}")
        if caselaw.notes:
            content_parts.append(f"Notes: {caselaw.notes[:500]}")
        if caselaw.text:
            content_parts.append(f"Opinion:\n{caselaw.text}")
        content_map[("caselaw", caselaw.id)] = "\n".join(content_parts)

    return manifest_items, content_map


def format_manifest_for_prompt(items: list[ManifestItem], token_budget: int) -> str:
    """Format manifest items into a compact text list for the selector prompt."""
    lines = [f"TOKEN BUDGET: ~{token_budget:,} tokens available for materials.\n"]

    for item in items:
        type_label = "DOC" if item.item_type == "document" else "CASE"
        date_str = f", {item.date}" if item.date else ""
        # Invert importance (DB uses 1=highest, 10=lowest) so the
        # LLM sees a higher number for more important items.
        priority = 11 - item.importance
        lines.append(
            f'[{type_label}-{item.item_id}] "{item.name}" '
            f"({item.category}{date_str}) - {item.description} "
            f"[~{item.word_count:,} words, priority: {priority}/10]"
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
                all_contents.append(content_map[key])
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

    # Build results
    selected_contents = []
    selected_key_set = set(selected_keys)
    unselected_items = []

    for item in manifest_items:
        key = (item.item_type, item.item_id)
        if key in selected_key_set and key in content_map:
            selected_contents.append(content_map[key])
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
        if item_type in ("document", "caselaw") and item_id is not None:
            keys.append((item_type, int(item_id)))

    return keys


def _fallback_by_importance(
    manifest_items: list[ManifestItem],
    content_map: dict,
    token_budget: int,
) -> list[tuple[str, int]]:
    """Fallback: select items by importance until budget is filled."""
    sorted_items = sorted(manifest_items, key=lambda x: x.importance)
    selected = []
    used_tokens = 0

    for item in sorted_items:
        key = (item.item_type, item.item_id)
        content = content_map.get(key, "")
        item_tokens = estimate_tokens(content)

        if used_tokens + item_tokens > token_budget:
            continue

        selected.append(key)
        used_tokens += item_tokens

    return selected
