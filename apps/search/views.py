from django.contrib.auth.decorators import login_required
from django.db.models import F, Func, Q, Value
from django.db.models.functions import Lower
from django.shortcuts import render
from watson import search as watson

from apps.contacts.models import Contact
from apps.intakes.models import Intake
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding
from apps.notes.models import Note


class RegexpReplace(Func):
    """PostgreSQL REGEXP_REPLACE function for normalizing strings."""

    function = "REGEXP_REPLACE"


def normalize_case_number(text):
    """Remove non-alphanumeric characters and lowercase for fuzzy case number matching."""
    return "".join(c.lower() for c in text if c.isalnum())


def search_proceedings_by_case_number(search_text):
    """
    Search proceedings by case number with fuzzy matching.

    Normalizes both the search term and case numbers by removing
    non-alphanumeric characters, allowing matches like:
    - "2024cv12345" matches "2024-CV-12345"
    - "cv12345" matches "CV-12345"
    """
    normalized_search = normalize_case_number(search_text)
    if not normalized_search:
        return Proceeding.objects.none()

    # Annotate with normalized case_number (strip non-alphanumeric, lowercase)
    return (
        Proceeding.objects.annotate(
            normalized_case_number=Lower(
                RegexpReplace(
                    F("case_number"), Value("[^a-zA-Z0-9]"), Value(""), Value("g")
                )
            )
        )
        .filter(normalized_case_number__icontains=normalized_search)
        .select_related("matter")
    )


# Available search scopes
SEARCH_SCOPES = [
    ("matters", "Matters", Matter),
    ("proceedings", "Proceedings", Proceeding),
    ("contacts", "Contacts", Contact),
    ("intakes", "Intakes", Intake),
    ("notes", "Notes", Note),
]

# Synonym mappings for search
SEARCH_SYNONYMS = {
    "contract": ["agreement"],
    "agreement": ["contract"],
}


def expand_search_with_synonyms(query):
    """Expand a search query with synonyms, returning list of search terms."""
    terms = [query]
    query_lower = query.lower()
    for word, synonyms in SEARCH_SYNONYMS.items():
        if word in query_lower:
            for synonym in synonyms:
                terms.append(query.lower().replace(word, synonym))
    return terms


@login_required
def index(request):
    active_scope = request.GET.get("scope") or request.session.get(
        "search_scope", "all"
    )
    context = {
        "app": "search",
        "action": "/search/results",
        "results": False,
        "scopes": SEARCH_SCOPES,
        "active_scope": active_scope,
    }
    return render(request, "search/content.html", context)


@login_required
def results(request):
    text = request.POST.get("search_text", "").strip()

    # Get active scope from POST (tab selection)
    scope = request.POST.get("scope", "all")
    scope_matters = scope in ("all", "matters")
    scope_proceedings = scope in ("all", "proceedings")
    scope_contacts = scope in ("all", "contacts")
    scope_intakes = scope in ("all", "intakes")
    scope_notes = scope in ("all", "notes")

    # Save to session for persistence
    request.session["search_scope"] = scope

    if not text:
        return render(
            request,
            "search/results.html",
            {
                "matters": None,
                "proceedings": None,
                "contacts": None,
                "intakes": None,
                "notes": None,
                "scopes": SEARCH_SCOPES,
                "active_scope": scope,
            },
        )

    matters = []
    proceedings = []
    contacts = []
    intakes = []
    notes = []

    # Digits only - use exact matching for IDs and phone numbers
    if text.isdigit():
        if scope_matters:
            matters = list(
                Matter.objects.filter(client_reference_id=text).order_by("name")
            )
        if scope_proceedings:
            proceedings = list(search_proceedings_by_case_number(text))
        if scope_contacts:
            contacts = list(
                Contact.objects.filter(
                    Q(phone1__contains=text)
                    | Q(phone2__contains=text)
                    | Q(phone3__contains=text)
                ).order_by("name")
            )
        if scope_intakes:
            intakes = list(Intake.objects.filter(phone__contains=text).order_by("name"))
        # Notes don't have phone numbers, skip for digit search
    else:
        # Expand search terms with synonyms
        search_terms = expand_search_with_synonyms(text)

        # Build list of models to search based on active scopes
        models_to_search = []
        if scope_matters:
            models_to_search.append(Matter)
        if scope_contacts:
            models_to_search.append(Contact)
        if scope_intakes:
            models_to_search.append(Intake)
        if scope_notes:
            models_to_search.append(Note)

        if models_to_search:
            # Use watson for fuzzy search
            seen_ids = {
                "matter": set(),
                "contact": set(),
                "intake": set(),
                "note": set(),
            }

            for term in search_terms:
                search_results = watson.search(term, models=tuple(models_to_search))

                for result in search_results:
                    obj = result.object
                    if isinstance(obj, Matter) and obj.id not in seen_ids["matter"]:
                        seen_ids["matter"].add(obj.id)
                        matters.append(obj)
                    elif isinstance(obj, Contact) and obj.id not in seen_ids["contact"]:
                        seen_ids["contact"].add(obj.id)
                        contacts.append(obj)
                    elif isinstance(obj, Intake) and obj.id not in seen_ids["intake"]:
                        seen_ids["intake"].add(obj.id)
                        intakes.append(obj)
                    elif isinstance(obj, Note) and obj.id not in seen_ids["note"]:
                        # Only include standalone notes (no matter)
                        if obj.matter is None:
                            seen_ids["note"].add(obj.id)
                            notes.append(obj)

            # Search proceedings by case number (fuzzy match)
            if scope_proceedings:
                proceedings = list(search_proceedings_by_case_number(text))

    context = {
        "app": "search",
        "action": "/search/results",
        "results": True,
        "matters": matters,
        "proceedings": proceedings,
        "contacts": contacts,
        "intakes": intakes,
        "notes": notes,
        "scopes": SEARCH_SCOPES,
        "active_scope": scope,
    }

    return render(request, "search/results.html", context)
