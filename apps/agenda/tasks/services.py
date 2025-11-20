"""Service functions for task operations."""

from apps.matters.models import Matter


def process_quick_task_description(description, last_matter_id=None):
    """
    Process a quick task description with intelligent matter matching.

    Args:
        description: The raw task description from user input
        last_matter_id: The matter ID from the last quick task (or None for Admin)

    Returns:
        tuple: (processed_description, matched_matter, use_smart_matching)
            - processed_description: Description with first word removed if it matched
            - matched_matter: Matter object to assign (or None for Admin)
            - use_smart_matching: Whether smart matching was used (vs filter matter)
    """
    description = description.strip()
    words = description.split(None, 1)  # Split on whitespace, max 2 parts

    matched_matter = None
    use_smart_matching = False

    if not words:
        return description, matched_matter, use_smart_matching

    first_word = words[0]

    # Check if first word is "Admin" - if so, explicitly set no matter
    if first_word.lower() == "admin":
        matched_matter = None  # Explicitly no matter
        use_smart_matching = True

        # Remove the first word from description
        if len(words) > 1:
            description = words[1]
        else:
            # If only "Admin", return empty description
            description = ""
    else:
        # Find matters whose name starts with the first word (case-insensitive)
        matching_matters = Matter.objects.filter(
            status__in=["Pending", "Open"], name__istartswith=first_word
        ).order_by("name")

        if matching_matters.exists():
            # Use the first match alphabetically
            matched_matter = matching_matters.first()
            use_smart_matching = True

            # Remove the first word from description if there are more words
            if len(words) > 1:
                description = words[1]
            else:
                # If only one word and it matched a matter, return empty description
                description = ""
        else:
            # No match found - use last matter from session
            use_smart_matching = True
            if last_matter_id:
                try:
                    matched_matter = Matter.objects.get(pk=last_matter_id)
                except Matter.DoesNotExist:
                    matched_matter = None
            # Don't remove first word since it wasn't a match

    return description, matched_matter, use_smart_matching
