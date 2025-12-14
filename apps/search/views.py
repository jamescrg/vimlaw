from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from watson import search as watson

from apps.contacts.models import Contact
from apps.intakes.models import Intake
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding

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
    context = {
        "app": "search",
        "action": "/search/results",
        "results": False,
    }
    return render(request, "search/content.html", context)


@login_required
def results(request):
    text = request.POST.get("search_text", "").strip()

    if not text:
        return render(
            request,
            "search/results.html",
            {"matters": None, "contacts": None, "proceedings": None, "intakes": None},
        )

    # Digits only - use exact matching for IDs and phone numbers
    if text.isdigit():
        matters = Matter.objects.filter(client_reference_id=text).order_by("name")
        contacts = Contact.objects.filter(
            Q(phone1__contains=text)
            | Q(phone2__contains=text)
            | Q(phone3__contains=text)
        ).order_by("name")
        proceedings = Proceeding.objects.filter(case_number__contains=text).order_by(
            "-status"
        )
        intakes = Intake.objects.filter(phone__contains=text).order_by("name")
    else:
        # Expand search terms with synonyms
        search_terms = expand_search_with_synonyms(text)

        # Use watson for fuzzy search, limited to global search models
        # Search with all synonym-expanded terms and combine results
        seen_ids = {
            "matter": set(),
            "contact": set(),
            "proceeding": set(),
            "intake": set(),
        }
        matters = []
        contacts = []
        proceedings = []
        intakes = []

        for term in search_terms:
            search_results = watson.search(
                term,
                models=(Matter, Contact, Proceeding, Intake),
            )

            for result in search_results:
                obj = result.object
                if isinstance(obj, Matter) and obj.id not in seen_ids["matter"]:
                    seen_ids["matter"].add(obj.id)
                    matters.append(obj)
                elif isinstance(obj, Contact) and obj.id not in seen_ids["contact"]:
                    seen_ids["contact"].add(obj.id)
                    contacts.append(obj)
                elif (
                    isinstance(obj, Proceeding) and obj.id not in seen_ids["proceeding"]
                ):
                    seen_ids["proceeding"].add(obj.id)
                    proceedings.append(obj)
                elif isinstance(obj, Intake) and obj.id not in seen_ids["intake"]:
                    seen_ids["intake"].add(obj.id)
                    intakes.append(obj)

    context = {
        "app": "search",
        "action": "/search/results",
        "results": True,
        "matters": matters,
        "contacts": contacts,
        "proceedings": proceedings,
        "intakes": intakes,
    }

    return render(request, "search/results.html", context)
