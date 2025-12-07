"""
Markdown list parser for outline import.
"""

import re

from django.db import models

from .models import OutlineItem


def parse_markdown_list(text):
    """
    Parse markdown unordered list into hierarchical structure.

    Supports:
    - Bullet markers: - and *
    - Indentation: spaces or tabs (2 spaces = 1 level)

    Returns list of dicts with 'content' and 'children' keys.
    """
    if not text or not text.strip():
        return []

    # Normalize tabs to 2 spaces
    text = text.replace("\t", "  ")
    lines = text.split("\n")

    result = []
    # Stack tracks (list_to_append_to, depth) for building hierarchy
    stack = [(result, -1)]

    for line in lines:
        # Skip empty lines
        if not line.strip():
            continue

        # Calculate indentation depth
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        depth = indent // 2  # 2 spaces per level

        # Extract content (remove bullet marker)
        match = re.match(r"^[-*]\s+(.*)$", stripped)
        if not match:
            # Line doesn't have a bullet marker, skip it
            continue

        content = match.group(1).strip()
        if not content:
            continue

        item = {"content": content, "children": []}

        # Pop stack until we find appropriate parent depth
        while stack and stack[-1][1] >= depth:
            stack.pop()

        # Add item to current parent's list
        parent_list = stack[-1][0]
        parent_list.append(item)

        # Push this item's children list onto stack
        stack.append((item["children"], depth))

    return result


def create_items_from_parsed(outline, parsed_items, parent=None, start_order=0):
    """
    Recursively create OutlineItem records from parsed structure.

    Args:
        outline: The Outline instance to add items to
        parsed_items: List of dicts with 'content' and 'children' keys
        parent: Parent OutlineItem (None for root items)
        start_order: Starting order number for items at this level
    """
    for i, item in enumerate(parsed_items):
        outline_item = OutlineItem.objects.create(
            outline=outline,
            parent=parent,
            content=item["content"],
            order=start_order + i,
        )
        if item.get("children"):
            create_items_from_parsed(
                outline, item["children"], parent=outline_item, start_order=0
            )


def import_markdown_to_outline(outline, markdown_text):
    """
    Parse markdown and create outline items, appending to existing items.

    Args:
        outline: The Outline instance to add items to
        markdown_text: Markdown text containing unordered list

    Returns:
        Number of items created
    """
    parsed = parse_markdown_list(markdown_text)
    if not parsed:
        return 0

    # Find the max order of existing root items to append after
    max_order = (
        OutlineItem.objects.filter(outline=outline, parent=None).aggregate(
            max_order=models.Max("order")
        )["max_order"]
        or -1
    )

    create_items_from_parsed(outline, parsed, parent=None, start_order=max_order + 1)

    # Count total items created (recursively)
    def count_items(items):
        total = len(items)
        for item in items:
            total += count_items(item.get("children", []))
        return total

    return count_items(parsed)
