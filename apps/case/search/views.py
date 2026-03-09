from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from watson import search as watson

from apps.case.models import Document, Fact, Highlight, Label
from apps.case.views import get_matter_from_url, get_session_key, set_last_tab
from apps.notes.models import Note

from .filters import SearchFilter

# Default scopes for case search
DEFAULT_SCOPES = ["documents", "highlights", "facts", "notes"]


def get_active_scopes(request, matter_id):
    """Get active search scopes from session, defaulting to all enabled."""
    key = get_session_key("search_scopes", matter_id)
    return request.session.get(key, DEFAULT_SCOPES)


def get_search_data(request, matter, matter_id):
    """Get search results with filters applied from session."""
    from datetime import datetime

    filter_session_key = get_session_key("search_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    active_scopes = get_active_scopes(request, matter_id)
    results = []
    query = filter_data.get("query", "").strip()

    if matter and query:
        # Use watson for fuzzy search across all three models
        search_results = watson.search(query)

        for result in search_results:
            obj = result.object
            result_item = None

            # Filter by matter, scope, and build result item
            if (
                isinstance(obj, Document)
                and obj.matter_id == matter.id
                and "documents" in active_scopes
            ):
                result_item = {
                    "type": "document",
                    "object": obj,
                    "rank": getattr(result, "watson_rank", 0),
                    "date": obj.date,
                }
            elif (
                isinstance(obj, Highlight)
                and obj.document.matter_id == matter.id
                and "highlights" in active_scopes
            ):
                result_item = {
                    "type": "highlight",
                    "object": obj,
                    "rank": getattr(result, "watson_rank", 0),
                    "date": obj.document.date,
                }
            elif (
                isinstance(obj, Fact)
                and obj.matter_id == matter.id
                and "facts" in active_scopes
            ):
                result_item = {
                    "type": "fact",
                    "object": obj,
                    "rank": getattr(result, "watson_rank", 0),
                    "date": obj.date,
                }
            elif (
                isinstance(obj, Note)
                and obj.matter_id == matter.id
                and "notes" in active_scopes
            ):
                result_item = {
                    "type": "note",
                    "object": obj,
                    "rank": getattr(result, "watson_rank", 0),
                    "date": obj.created_at.date() if obj.created_at else None,
                }

            if result_item:
                results.append(result_item)

        category = filter_data.get("category", "")
        if category:
            filtered = []
            for r in results:
                if r["type"] == "document" and r["object"].category == category:
                    filtered.append(r)
                elif r["type"] == "highlight":
                    if r["object"].document.category == category:
                        filtered.append(r)
                # Facts don't have category, exclude when filtering by category
            results = filtered

        label_id = filter_data.get("label", "")
        if label_id:
            try:
                label_id = int(label_id)
                results = [
                    r
                    for r in results
                    if hasattr(r["object"], "labels")
                    and r["object"].labels.filter(id=label_id).exists()
                ]
            except (ValueError, TypeError):
                pass

        document_id = filter_data.get("document", "")
        if document_id:
            try:
                document_id = int(document_id)
                filtered = []
                for r in results:
                    if r["type"] == "document" and r["object"].id == document_id:
                        filtered.append(r)
                    elif r["type"] == "highlight":
                        if r["object"].document_id == document_id:
                            filtered.append(r)
                    elif r["type"] == "fact":
                        if r["object"].documents.filter(id=document_id).exists():
                            filtered.append(r)
                results = filtered
            except (ValueError, TypeError):
                pass

        date_from = filter_data.get("date_from", "")
        if date_from:
            try:
                date_from = datetime.strptime(date_from, "%Y-%m-%d").date()
                results = [r for r in results if r["date"] and r["date"] >= date_from]
            except (ValueError, TypeError):
                pass

        date_to = filter_data.get("date_to", "")
        if date_to:
            try:
                date_to = datetime.strptime(date_to, "%Y-%m-%d").date()
                results = [r for r in results if r["date"] and r["date"] <= date_to]
            except (ValueError, TypeError):
                pass

        importance = filter_data.get("importance", "")
        if importance:
            try:
                importance = int(importance)
                results = [r for r in results if r["object"].importance <= importance]
            except (ValueError, TypeError):
                pass

    # Get labels and documents for filter panel
    labels = (
        Label.objects.filter(Q(matter=matter) | Q(matter__isnull=True)).order_by("name")
        if matter
        else []
    )

    documents = (
        Document.objects.filter(matter=matter).order_by("name") if matter else []
    )

    # Create filter object for rendering the form
    filter_obj = SearchFilter(filter_data, matter=matter)

    # Get counts for empty state
    doc_count = Document.objects.filter(matter=matter).count() if matter else 0
    highlight_count = (
        Highlight.objects.filter(document__matter=matter).count() if matter else 0
    )
    fact_count = Fact.objects.filter(matter=matter).count() if matter else 0
    note_count = Note.objects.filter(matter=matter).count() if matter else 0

    return {
        "results": results,
        "query": query,
        "labels": labels,
        "documents": documents,
        "filter_data": filter_data,
        "filter": filter_obj,
        "active_scopes": active_scopes,
        "doc_count": doc_count,
        "highlight_count": highlight_count,
        "fact_count": fact_count,
        "note_count": note_count,
    }


@login_required
def search_index(request, matter_id):
    """Main search view with persistent filter panel."""
    matter, matters = get_matter_from_url(request, matter_id)
    set_last_tab(request, matter_id, "search")

    context = {
        "app": "matters",
        "subapp": "search",
        "matter": matter,
        "matters": matters,
    } | get_search_data(request, matter, matter_id)

    return render(request, "case/search/main.html", context)


@login_required
def search_list(request, matter_id):
    """HTMX partial for full search content area."""
    matter, matters = get_matter_from_url(request, matter_id)

    context = {
        "app": "matters",
        "subapp": "search",
        "matter": matter,
        "matters": matters,
    } | get_search_data(request, matter, matter_id)

    return render(request, "case/search/list.html", context)


@login_required
def search_results(request, matter_id):
    """HTMX partial for search results only."""
    matter, _ = get_matter_from_url(request, matter_id)
    context = {"matter": matter} | get_search_data(request, matter, matter_id)
    return render(request, "case/search/results.html", context)


@login_required
def search_query(request, matter_id):
    """Handle search query input via HTMX."""
    matter, _ = get_matter_from_url(request, matter_id)
    filter_session_key = get_session_key("search_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    query = request.POST.get("query", "").strip()
    filter_data["query"] = query
    request.session[filter_session_key] = filter_data

    # Handle scope checkboxes
    scope_documents = request.POST.get("scope_documents") == "on"
    scope_highlights = request.POST.get("scope_highlights") == "on"
    scope_facts = request.POST.get("scope_facts") == "on"
    scope_notes = request.POST.get("scope_notes") == "on"

    # If any scope checkbox was sent, update scopes; otherwise keep existing
    if any(key.startswith("scope_") for key in request.POST.keys() if key != "query"):
        # If no scopes selected, enable all
        if not any([scope_documents, scope_highlights, scope_facts, scope_notes]):
            active_scopes = DEFAULT_SCOPES
        else:
            active_scopes = []
            if scope_documents:
                active_scopes.append("documents")
            if scope_highlights:
                active_scopes.append("highlights")
            if scope_facts:
                active_scopes.append("facts")
            if scope_notes:
                active_scopes.append("notes")

        scope_session_key = get_session_key("search_scopes", matter_id)
        request.session[scope_session_key] = active_scopes

    context = {"matter": matter} | get_search_data(request, matter, matter_id)
    context["is_htmx"] = True
    return render(request, "case/search/results.html", context)


@login_required
def search_filter(request, matter_id):
    """Filter panel update - POST saves, GET renders panel."""
    matter, _ = get_matter_from_url(request, matter_id)
    filter_session_key = get_session_key("search_filter", matter_id)

    if request.method == "POST":
        filter_data = request.session.get(filter_session_key, {})
        # Update filter data with form values, preserving query
        for key, value in request.POST.items():
            if key != "csrfmiddlewaretoken":
                if value:
                    filter_data[key] = value
                else:
                    filter_data.pop(key, None)
        request.session[filter_session_key] = filter_data
        return HttpResponse(status=204, headers={"HX-Trigger": "searchChanged"})

    # GET - render filter panel
    filter_data = request.session.get(filter_session_key, {})
    filter_obj = SearchFilter(filter_data, matter=matter)

    return render(
        request,
        "case/search/filter-panel.html",
        {"filter": filter_obj, "matter": matter, "filter_data": filter_data},
    )


@login_required
def search_filter_type(request, matter_id, result_type=None):
    """Quick filter by result type."""
    filter_session_key = get_session_key("search_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    if result_type:
        filter_data["result_type"] = result_type
    else:
        filter_data.pop("result_type", None)

    request.session[filter_session_key] = filter_data
    return HttpResponse(status=204, headers={"HX-Trigger": "searchChanged"})


@login_required
def search_clear(request, matter_id):
    """Clear search query and all filters."""
    filter_session_key = get_session_key("search_filter", matter_id)
    request.session[filter_session_key] = {}
    return HttpResponse(status=204, headers={"HX-Trigger": "searchChanged"})
