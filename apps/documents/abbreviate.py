import re

# --- Combined T.6 (Parties) & T.16 (Document Types) Abbreviation Map ---
# NOTE: The keys are lowercased for case-insensitive matching.
ABBREVIATION_MAP = {
    # T.6 Party/Institutional Indicators frequently found in titles
    "plaintiff": "Pl.",
    "defendant": "Def.",
    "appellee": "Appellee",  # Keep spelled out to avoid ambiguity with App.
    "appellant": "Appellant",  # Keep spelled out to avoid ambiguity with App.
    "corporation": "Corp.",
    "incorporated": "Inc.",
    "association": "Ass'n",
    "company": "Co.",
    "limited": "Ltd.",
    # T.16 Document Types and Subdivisions
    "affidavit": "Aff.",
    "amendment": "Amend.",
    "answer": "Answer",  # T.16 lists 'Answer' as spelled out
    "appendix": "App.",
    "article": "Art.",
    "brief": "Br.",
    "certificate": "Cert.",
    "claim": "Claim",
    "complaint": "Compl.",
    "declaration": "Decl.",
    "deposition": "Dep.",
    "exhibit": "Ex.",
    "interrogatories": "Interrog.",
    "interrogatory": "Interrog.",
    "memorandum": "Mem.",
    "motion": "Mot.",
    "opposition": "Opp'n",
    "paragraph": "Para.",
    "petition": "Pet.",
    "record": "R.",
    "reply": "Reply",
    "request": "Req.",
    "response": "Resp.",
    "section": "§",
    "stipulation": "Stip.",
    "subpoena": "Subp.",
    "summary": "Summ.",
    "supplement": "Supp.",
    "transcript": "Tr.",
    "volume": "Vol.",
    # Common T.6/T.13 words often used in titles
    "judgment": "J.",
    "law": "L.",
    "letter": "Ltr.",
    "order": "Order",  # Often not abbreviated
}

# --- Connecting Words to Omit (Rule 10.2.1(a)) ---
# These words are generally not abbreviated or are omitted entirely.
SHORT_WORDS_TO_OMIT = {"for", "the", "of", "and", "in", "on", "a"}


def bluebook_abbreviate(title: str) -> str:
    """
    Abbreviates words in a court document title according to The Bluebook Rules
    (primarily T.16 for document types and Rule 10.2.1 for omissions).

    Args:
        title: The full title of the court document (e.g., "Plaintiff's Motion
               for Summary Judgment and Incorporated Memorandum of Law").

    Returns:
        The abbreviated document title string (e.g., "Pl.'s Mot. Summ. J.
        & Inc. Mem. L.").
    """
    # 1. Split the title by spaces, while preserving separators and punctuation
    # This regex attempts to find words, numbers, and common punctuation/separators
    words = re.findall(r"[\w.'&/]+|v\.|et al\.|,|;", title)

    abbreviated_words = []

    # Track the first word for the "first word not abbreviated" rule.
    is_first_word = True

    for word in words:
        # Check for possessive and strip it for lookup
        is_possessive = word.lower().endswith("'s")
        if is_possessive:
            base_word = re.sub(r"'s$", "", word, flags=re.IGNORECASE).lower()
        else:
            base_word = re.sub(r"['.]*$", "", word).lower()

        # --- Rule 10.2.2: Omit short connecting words ---
        if base_word in SHORT_WORDS_TO_OMIT:
            # Rule 10.2.1(a) requires 'and' to be replaced by '&' if not first word
            if base_word == "and" and not is_first_word:
                abbreviated_words.append("&")
            # Otherwise, skip 'for', 'the', 'of', 'in', 'on', 'a'
            continue

        # --- Rule 10.2.2: Do not abbreviate the first word ---
        # if is_first_word:
        #     abbreviated_words.append(word)
        #     is_first_word = False
        #     continue

        # --- Rule 10.2.2 & T.16: Apply specific abbreviations ---
        if base_word in ABBREVIATION_MAP:
            abbreviated_word = ABBREVIATION_MAP[base_word]

            # Handle possessives (e.g., Plaintiff's -> Pl.'s)
            if is_possessive:
                if abbreviated_word.endswith("."):
                    abbreviated_word = abbreviated_word[:-1] + "'s"
                else:
                    abbreviated_word = abbreviated_word + "'s"

            abbreviated_words.append(abbreviated_word)

        # --- Catchall: Abbreviate words of 8 letters or more to 3 letters ---
        elif len(base_word) >= 8:
            # Abbreviate to first 3 letters, capitalized, with period
            abbreviated_word = base_word[:3].capitalize() + "."
            if is_possessive:
                abbreviated_word = abbreviated_word[:-1] + "'s"
            abbreviated_words.append(abbreviated_word)

        # --- No abbreviation needed (proper nouns, non-T.6/T.16 words < 8 letters) ---
        else:
            abbreviated_words.append(word)

    # 2. Join the words back into a single string
    result = " ".join(abbreviated_words)

    # 3. Clean up spacing before punctuation and specific terms
    result = re.sub(r"\s([,.;&])", r"\1", result)
    result = re.sub(r" '\s", "'", result)
    return result
