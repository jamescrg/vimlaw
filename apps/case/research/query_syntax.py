"""CourtListener query syntax guidance shared by every prompt that writes
search queries: the research pipeline's query refiner and the research
chat's tool loop. One copy so syntax fixes propagate everywhere."""

COURTLISTENER_SYNTAX_RULES = (
    "CourtListener search syntax (Solr-based):\n"
    "- AND (or &): intersection (AND is the default between terms)\n"
    "- OR: union of alternatives\n"
    "- NOT (or - prefix): exclude terms\n"
    '- "quoted phrase": exact phrase match, no stemming\n'
    "- (parentheses): group expressions, may be nested\n"
    '- "phrase"~N: proximity — words within N words of each other (ONLY after quoted phrases)\n'
    "- term~: fuzzy match for spelling variations (no number after ~)\n"
    "- stem*: wildcard prefix matching — matches all words starting with the stem\n"
    "  Examples: waiv* → waive, waived, waiver; negligen* → negligence, negligent, negligently\n"
    "  Use wildcards instead of OR-listing inflections of the same word:\n"
    "  BAD:  (waive OR waived OR waiver OR waiving)\n"
    "  GOOD: waiv*\n"
    "  OR groups are still correct for genuinely different terms (e.g. suit OR action)\n\n"
    "CRITICAL SYNTAX RULES — violating these causes server errors:\n"
    "- The ~ operator ONLY works two ways:\n"
    '  1. "quoted phrase"~N → proximity (OK: "summary judgment"~5)\n'
    "  2. word~ → fuzzy spelling (OK: negligen~)\n"
    "- NEVER write word~N (e.g. motion~3) — this is INVALID and will crash the search\n"
    "- NEVER use ~ between or after bare words for proximity — use quoted phrases instead\n"
    "- Parentheses MUST be balanced\n"
    "- Quotes MUST be balanced\n"
    "- Do NOT use fielded search (e.g. court_id:) — court filtering is handled separately\n"
    "- Do NOT use range queries [x TO y] — not supported on the full-text search field\n\n"
    "Guidelines:\n"
    "- Use stem* wildcards for word inflections instead of OR-listing every form\n"
    '- Use OR groups for genuinely different terms or phrases (e.g. suit OR action OR "cause of action")\n'
    "- Use proximity operators on quoted phrases for multi-word concepts\n"
    "- Group related concepts with parentheses and connect groups with AND\n"
    "- Keep the query under 3 levels of nesting to avoid complexity issues\n"
    "- Keep the query concise — 120 characters or fewer\n\n"
)

# Term selection, not syntax: what makes a query GOOD. Shared with the
# research chat's tool loop; grew out of run 892 (five rephrasings of one
# concept set, a subsectioned statute cite, and 'after' as a keyword).
QUERY_DESIGN_RULES = (
    "QUERY DESIGN (what to search, not how to spell it):\n"
    "- Every term must be a word a COURT would write in the controlling "
    "paragraph of an opinion. Never use narrative or procedural filler "
    "words: after, before, during, following, provide, obtain, response, "
    "party, case. They match everything and distinguish nothing.\n"
    "- Search the doctrine's own language. Statutes and leading opinions "
    "have operative phrases; quote those, not a description of your "
    'situation. ("expenses of the motion" beats fees AND compel.)\n'
    "- Statute numbers: a bare quoted number works — courts write the "
    'number in text ("9-11-37"). NEVER include subsections '
    '("9-11-37(a)(4)(A)"): punctuation makes matching unreliable and '
    "over-narrow. Pair the number with doctrine vocabulary instead: "
    '("9-11-37" OR "motion to compel").\n'
    "- 2-3 concept groups per query, connected with AND; each group is "
    "one concept expressed as its best term of art plus true synonyms. "
    "More groups makes queries brittle, not precise.\n"
    "- ONE NEW CONCEPT PER QUERY: a follow-up search must change WHAT is "
    "asked — a different element, a different doctrine, a different "
    "synonym family — never a reshuffle of the same terms. If your next "
    "query would share most of its terms with one you already ran, do "
    "not run it: triage the results you already have, or re-run one "
    "query with a larger num_results.\n"
    "- Prefer stem* wildcards to OR-lists of inflections (moot* covers "
    "moot, mooted, mootness).\n\n"
)
