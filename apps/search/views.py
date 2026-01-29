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


def get_active_scopes(request):
    """Get active search scopes from session, defaulting to all enabled."""
    default_scopes = ["matters", "proceedings", "contacts", "intakes", "notes"]
    stored_scopes = request.session.get("search_scopes")

    if stored_scopes is None:
        return default_scopes

    # Add any new default scopes that weren't in the stored session
    # (e.g., "proceedings" added after user's last search)
    for scope in default_scopes:
        if scope not in stored_scopes:
            stored_scopes.append(scope)

    return stored_scopes


@login_required
def index(request):
    active_scopes = get_active_scopes(request)
    context = {
        "app": "search",
        "action": "/search/results",
        "results": False,
        "scopes": SEARCH_SCOPES,
        "active_scopes": active_scopes,
    }
    return render(request, "search/content.html", context)


@login_required
def results(request):
    text = request.POST.get("search_text", "").strip()

    # Get scope filters from POST (checkboxes)
    scope_matters = request.POST.get("scope_matters") == "on"
    scope_proceedings = request.POST.get("scope_proceedings") == "on"
    scope_contacts = request.POST.get("scope_contacts") == "on"
    scope_intakes = request.POST.get("scope_intakes") == "on"
    scope_notes = request.POST.get("scope_notes") == "on"

    # If no scopes selected, enable all (first load or all unchecked)
    all_scopes = [
        scope_matters,
        scope_proceedings,
        scope_contacts,
        scope_intakes,
        scope_notes,
    ]
    if not any(all_scopes):
        scope_matters = scope_proceedings = scope_contacts = True
        scope_intakes = scope_notes = True

    # Save to session for persistence
    active_scopes = []
    if scope_matters:
        active_scopes.append("matters")
    if scope_proceedings:
        active_scopes.append("proceedings")
    if scope_contacts:
        active_scopes.append("contacts")
    if scope_intakes:
        active_scopes.append("intakes")
    if scope_notes:
        active_scopes.append("notes")
    request.session["search_scopes"] = active_scopes

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
                "active_scopes": active_scopes,
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
        "active_scopes": active_scopes,
    }

    return render(request, "search/results.html", context)
