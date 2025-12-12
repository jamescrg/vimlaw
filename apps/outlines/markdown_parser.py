"""
Markdown list parser for outline import/export.
"""

import re

from django.db import models

from .models import OutlineItem


def export_highlight_colors(text):
    """Convert colored highlights to standard markdown with HTML comment metadata.

    g==text== → ==text==<!-- hl:g -->
    r==text== → ==text==<!-- hl:r -->
    c==text== → ==text==<!-- hl:c -->
    """
    return re.sub(r"([grc])==(.+?)==", r"==\2==<!-- hl:\1 -->", text)


def restore_highlight_colors(text):
    """Restore colored highlights from HTML comment metadata on import.

    ==text==<!-- hl:g --> → g==text==
    ==text==<!-- hl:r --> → r==text==
    ==text==<!-- hl:c --> → c==text==
    """
    return re.sub(r"==(.+?)==<!-- hl:([grc]) -->", r"\2==\1==", text)


def parse_markdown_list(text):
    """
    Parse markdown unordered list into hierarchical structure.

    Supports:
    - Bullet markers: - and *
    - Markdown headings: # ## ### etc. (converted to heading=True)
    - Indentation: spaces or tabs (2 spaces = 1 level)
    - Colored highlight restoration: ==text==<!-- hl:g --> → g==text==

    Returns list of dicts with 'content', 'children', and 'heading' keys.
    Headings can appear at any nesting level.
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

        # Check for markdown heading (# ## ### etc.)
        heading_match = re.match(r"^(#{1,})\s+(.*)$", stripped)
        if heading_match:
            content = heading_match.group(2).strip()
            if not content:
                continue
            content = restore_highlight_colors(content)
            item = {"content": content, "children": [], "heading": True}

            # Pop stack until we find appropriate parent depth
            while stack and stack[-1][1] >= depth:
                stack.pop()

            # Add item to current parent's list
            parent_list = stack[-1][0]
            parent_list.append(item)

            # Push this item's children list onto stack
            stack.append((item["children"], depth))
            continue

        # Extract content (remove bullet marker)
        match = re.match(r"^[-*]\s+(.*)$", stripped)
        if not match:
            # Line doesn't have a bullet marker, skip it
            continue

        content = match.group(1).strip()
        if not content:
            continue
        content = restore_highlight_colors(content)

        item = {"content": content, "children": [], "heading": False}

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
        parsed_items: List of dicts with 'content', 'children', and 'heading' keys
        parent: Parent OutlineItem (None for root items)
        start_order: Starting order number for items at this level
    """
    for i, item in enumerate(parsed_items):
        outline_item = OutlineItem.objects.create(
            outline=outline,
            parent=parent,
            content=item["content"],
            order=start_order + i,
            heading=item.get("heading", False),
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

    # Delete empty root items (e.g., the initial empty item created with new outlines)
    OutlineItem.objects.filter(outline=outline, parent=None, content="").delete()

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


def export_outline_to_markdown(outline):
    """
    Export outline items to markdown format.

    Args:
        outline: The Outline instance to export

    Returns:
        Markdown string representation of the outline

    Headings are exported as markdown headings with level derived from depth:
    - depth 0 → ## (h2)
    - depth 1 → ### (h3)
    - depth 2 → #### (h4)
    - etc.
    Regular items are exported as indented bullet lists.
    """

    def get_sources_text(item):
        """Get citations for item sources as space-separated text."""
        citations = []
        for doc in item.documents.all():
            citations.append(doc.citation)
        for hl in item.highlights.all():
            citations.append(hl.citation)
        return " ".join(citations)

    def export_item(item, depth=0, is_first=False):
        """Recursively export an item and its children."""
        lines = []
        sources = get_sources_text(item)
        content = export_highlight_colors(item.content)
        content_with_sources = f"{content} {sources}" if sources else content

        if item.heading:
            # Add blank line before heading (unless it's the first item)
            if not is_first:
                lines.append("")
            # Export as markdown heading with level derived from depth
            # depth 0 → ##, depth 1 → ###, depth 2 → ####, etc.
            heading_level = min(depth + 2, 6)  # Cap at h6
            hashes = "#" * heading_level
            lines.append(f"{hashes} {content_with_sources}")
            # Add blank line after heading
            lines.append("")
            # Children of headings continue at depth + 1
            for i, child in enumerate(item.children.all().order_by("order")):
                lines.extend(export_item(child, depth + 1, is_first=(i == 0)))
        else:
            indent = "  " * depth
            lines.append(f"{indent}- {content_with_sources}")
            # Export children with increased depth
            for i, child in enumerate(item.children.all().order_by("order")):
                lines.extend(export_item(child, depth + 1, is_first=False))

        return lines

    # Get root items
    root_items = outline.items.filter(parent=None).order_by("order")

    lines = []
    for i, item in enumerate(root_items):
        lines.extend(export_item(item, depth=0, is_first=(i == 0)))

    # Remove consecutive blank lines and trailing blank lines
    result = []
    for line in lines:
        if line == "" and result and result[-1] == "":
            continue  # Skip consecutive blank lines
        result.append(line)

    while result and result[-1] == "":
        result.pop()

    return "\n".join(result)
