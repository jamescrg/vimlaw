"""Service functions for task operations."""

from difflib import get_close_matches

from apps.matters.models import Matter


def process_quick_task_description(description, last_matter_id=None):
    """
    Process a quick task description with intelligent matter matching.

    Supports two matching modes:
    1. Semicolon notation: "Matter Name; task description" - fuzzy matches matter name
    2. First word: "MatterWord task description" - exact match on first word

    Args:
        description: The raw task description from user input
        last_matter_id: The matter ID from the last quick task (or None for Admin)

    Returns:
        tuple: (processed_description, matched_matter, use_smart_matching)
            - processed_description: Description with prefix removed if it matched
            - matched_matter: Matter object to assign (or None for Admin)
            - use_smart_matching: Whether smart matching was used (vs filter matter)
    """
    description = description.strip()
    matched_matter = None
    use_smart_matching = False

    # Check for semicolon notation first (e.g., "Smith Estate; review will")
    if ";" in description:
        prefix, remainder = description.split(";", 1)
        prefix = prefix.strip()
        remainder = remainder.strip()

        # Always use the remainder as the description when semicolon is present
        description = remainder if remainder else ""

        # Check if prefix is "Admin"
        if prefix.lower() == "admin":
            matched_matter = None
            use_smart_matching = True
        else:
            # Get all open/pending matters for fuzzy matching
            matters = Matter.objects.filter(status__in=["Pending", "Open"])

            # Build a list of (name, matter_object) tuples
            matters_list = [(m.name, m) for m in matters]
            matter_names = [name for name, _ in matters_list]

            # Convert prefix to lowercase for case-insensitive matching
            prefix_lower = prefix.lower()

            # Tier 1: Fuzzy match against full matter names (case-insensitive)
            # cutoff=0.6 means 60% similarity required
            matter_names_lower = [name.lower() for name in matter_names]
            matches = get_close_matches(
                prefix_lower, matter_names_lower, n=1, cutoff=0.6
            )

            if not matches:
                # Tier 2: Fuzzy match against first word only
                first_words = [
                    name.split()[0].lower() if name.split() else ""
                    for name in matter_names
                ]
                matches = get_close_matches(prefix_lower, first_words, n=1, cutoff=0.6)

                if matches:
                    # Find the matter with the matched first word
                    matched_first_word = matches[0]
                    matched_matter = next(
                        (
                            m
                            for name, m in matters_list
                            if name.split()[0].lower() == matched_first_word
                        ),
                        None,
                    )
                    use_smart_matching = True

            if matches and not matched_matter:
                # Tier 1 match found - find the matter with the matched full name
                matched_name_lower = matches[0]
                matched_matter = next(
                    (
                        m
                        for name, m in matters_list
                        if name.lower() == matched_name_lower
                    ),
                    None,
                )
                use_smart_matching = True

            if not matched_matter and not use_smart_matching:
                # No match found, use last matter from session
                use_smart_matching = True
                if last_matter_id:
                    try:
                        matched_matter = Matter.objects.get(pk=last_matter_id)
                    except Matter.DoesNotExist:
                        matched_matter = None

        # Semicolon notation always uses smart matching
        return description, matched_matter, use_smart_matching

    # No semicolon - use last matter from session if available
    if last_matter_id:
        use_smart_matching = True
        try:
            matched_matter = Matter.objects.get(pk=last_matter_id)
        except Matter.DoesNotExist:
            matched_matter = None

    return description, matched_matter, use_smart_matching

    # ========================================================================
    # FIRST-WORD MATCHING (DISABLED - kept for reference)
    # ========================================================================
    # words = description.split(None, 1)  # Split on whitespace, max 2 parts
    #
    # if not words:
    #     return description, matched_matter, use_smart_matching
    #
    # first_word = words[0]
    #
    # # Check if first word is "Admin" - if so, explicitly set no matter
    # if first_word.lower() == "admin":
    #     matched_matter = None  # Explicitly no matter
    #     use_smart_matching = True
    #
    #     # Remove the first word from description
    #     if len(words) > 1:
    #         description = words[1]
    #     else:
    #         # If only "Admin", return empty description
    #         description = ""
    # else:
    #     # Find matters whose name starts with the first word (case-insensitive)
    #     matching_matters = Matter.objects.filter(
    #         status__in=["Pending", "Open"], name__istartswith=first_word
    #     ).order_by("name")
    #
    #     if matching_matters.exists():
    #         # Use the first match alphabetically
    #         matched_matter = matching_matters.first()
    #         use_smart_matching = True
    #
    #         # Remove the first word from description if there are more words
    #         if len(words) > 1:
    #             description = words[1]
    #         else:
    #             # If only one word and it matched a matter, return empty description
    #             description = ""
    #     else:
    #         # No match found - use last matter from session
    #         use_smart_matching = True
    #         if last_matter_id:
    #             try:
    #                 matched_matter = Matter.objects.get(pk=last_matter_id)
    #             except Matter.DoesNotExist:
    #                 matched_matter = None
    #         # Don't remove first word since it wasn't a match
    #
    # return description, matched_matter, use_smart_matching
