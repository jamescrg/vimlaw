#!/usr/bin/env python3
"""
Migrate Bootstrap Icons to Lucide Icons.

Bootstrap pattern: <i class="bi bi-icon-name"></i>
Lucide pattern: <i class="icon-icon-name"></i>
"""

import os
import re

# Mapping from Bootstrap icon names to Lucide icon names
# Format: 'bootstrap-name': 'lucide-name'
ICON_MAP = {
    # Navigation arrows
    "arrow-bar-up": "arrow-up-to-line",
    "arrow-down-up": "arrow-down-up",
    "arrow-left": "arrow-left",
    "arrow-left-circle": "arrow-left-circle",
    "arrow-repeat": "refresh-cw",
    "arrow-right-circle": "arrow-right-circle",
    "arrow-up-left-circle": "arrow-up-left",
    "arrow-up-right-circle": "arrow-up-right",
    "arrows-collapse": "minimize-2",
    "arrows-expand": "maximize-2",
    # Box arrows (external links, uploads, downloads)
    "box-arrow-down": "download",
    "box-arrow-in-up": "upload",
    "box-arrow-up-right": "external-link",
    # Business/work
    "briefcase": "briefcase",
    "briefcase-fill": "briefcase",
    # Calendar
    "calendar-check": "calendar-check",
    "calendar-event": "calendar",
    "calendar-plus": "calendar-plus",
    "calendar-week": "calendar-days",
    # Carets/Chevrons
    "caret-up": "chevron-up",
    "chevron-contract": "chevrons-down-up",
    "chevron-down": "chevron-down",
    "chevron-expand": "chevrons-up-down",
    "chevron-left": "chevron-left",
    "chevron-right": "chevron-right",
    "chevron-up": "chevron-up",
    # Chat/Communication
    "chat-dots": "message-circle",
    "envelope": "mail",
    "send": "send",
    "telephone": "phone",
    "telephone-outbound": "phone-outgoing",
    # Checks and X marks
    "check": "check",
    "check-circle-fill": "circle-check",
    "check-lg": "check",
    "check-square": "square-check",
    "check2-square": "square-check",
    "x": "x",
    "x-circle": "x-circle",
    "x-circle-fill": "circle-x",
    "x-lg": "x",
    # Clipboard
    "clipboard": "clipboard",
    "clipboard-plus": "clipboard-plus",
    # Cloud
    "cloud-arrow-up": "cloud-upload",
    "cloud-check": "cloud-check",
    "cloud-download": "cloud-download",
    "cloud-slash": "cloud-off",
    "cloud-upload": "cloud-upload",
    # Code
    "code-square": "code",
    # Circle icons
    "dash-circle": "minus-circle",
    # Files and documents
    "download": "download",
    "file-break": "file",
    "file-earmark": "file",
    "file-earmark-pdf": "file-text",
    "file-earmark-spreadsheet": "file-spreadsheet",
    "file-earmark-text": "file-text",
    "file-pdf": "file-text",
    "file-text": "file-text",
    "files": "files",
    "filetype-pdf": "file-text",
    # Alerts/Warnings
    "exclamation-circle-fill": "alert-circle",
    "exclamation-square": "alert-triangle",
    "exclamation-triangle": "alert-triangle",
    "exclamation-triangle-fill": "alert-triangle",
    # View/Eye
    "eye": "eye",
    # Filter/Sort
    "filter": "filter",
    "funnel": "filter",
    "sort-up-alt": "arrow-up-down",
    # Flags
    "flag": "flag",
    "flag-fill": "flag",
    # Folders
    "folder": "folder",
    # Settings/Gear
    "gear": "settings",
    # Location
    "geo-alt": "map-pin",
    "globe": "globe",
    # UI elements
    "grip-vertical": "grip-vertical",
    "highlighter": "highlighter",
    "hourglass-split": "hourglass",
    "house": "house",
    "inbox": "inbox",
    "info-circle-fill": "info",
    # Journal/Notes
    "journal-plus": "book-plus",
    "journal-text": "book-text",
    # Keyboard
    "keyboard": "keyboard",
    # Layout
    "layout-sidebar": "panel-left",
    "layout-sidebar-reverse": "panel-right",
    # Light/Ideas
    "lightbulb": "lightbulb",
    # Links
    "link-45deg": "link",
    "paperclip": "paperclip",
    # Edit
    "pencil": "pencil",
    "pencil-square": "square-pen",
    # People
    "people": "users",
    "person": "user",
    "person-check": "user-check",
    "person-circle": "user-circle",
    "person-plus": "user-plus",
    # Plus icons
    "plus-circle": "plus-circle",
    "plus-download": "download",
    "plus-lg": "plus",
    # Print
    "printer": "printer",
    # Quote
    "quote": "quote",
    # Receipt
    "receipt": "receipt",
    # Robot/AI
    "robot": "bot",
    # Search
    "search": "search",
    # Shapes
    "square": "square",
    # Sticky/Notes
    "sticky": "sticky-note",
    # Tags
    "tag": "tag",
    # Menu/More
    "three-dots-vertical": "ellipsis-vertical",
    # Toggle
    "toggle-on": "toggle-right",
    # Trash
    "trash": "trash-2",
    # Typography
    "type-h2": "heading-2",
}


def migrate_file(filepath):
    """Migrate Bootstrap icons to Lucide in a single file."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    original = content

    # Pattern to match Bootstrap icon classes
    # Matches: bi bi-icon-name or just bi-icon-name
    for bs_icon, lucide_icon in ICON_MAP.items():
        # Replace "bi bi-icon-name" with "icon-lucide-name"
        content = re.sub(
            rf"\bbi bi-{re.escape(bs_icon)}\b", f"icon-{lucide_icon}", content
        )
        # Replace standalone "bi-icon-name" (in JS strings, etc.)
        content = re.sub(
            rf'(["\'])bi-{re.escape(bs_icon)}(["\'])',
            rf"\1icon-{lucide_icon}\2",
            content,
        )

    if content != original:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    return False


def main():
    """Main migration function."""
    base_dir = "/home/james/law"

    # Directories to process
    dirs_to_process = [
        os.path.join(base_dir, "templates"),
        os.path.join(base_dir, "static/js"),
        os.path.join(base_dir, "static/css"),
    ]

    # File extensions to process
    extensions = {".html", ".js", ".css"}

    modified_files = []

    for dir_path in dirs_to_process:
        for root, dirs, files in os.walk(dir_path):
            for filename in files:
                ext = os.path.splitext(filename)[1]
                if ext in extensions:
                    filepath = os.path.join(root, filename)
                    if migrate_file(filepath):
                        modified_files.append(filepath)
                        print(f"Modified: {filepath}")

    print(f"\nTotal files modified: {len(modified_files)}")


if __name__ == "__main__":
    main()
