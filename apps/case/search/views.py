from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from watson import search as watson

from apps.case.documents.get_document_data import get_selected_matter
from apps.case.models import Document, Fact, Highlight, Label

from .filters import SearchFilter


def get_search_data(request, matter):
    """Get search results with filters applied from session."""
    from datetime import datetime

    filter_data = request.session.get("search_filter", {})
    results = []
    query = filter_data.get("query", "").strip()

    if matter and query:
        # Use watson for fuzzy search across all three models
        search_results = watson.search(query)

        for result in search_results:
            obj = result.object
            result_item = None

            # Filter by matter and build result item
            if isinstance(obj, Document) and obj.matter_id == matter.id:
                result_item = {
                    "type": "document",
                    "object": obj,
                    "rank": getattr(result, "watson_rank", 0),
                    "date": obj.date,
                }
            elif isinstance(obj, Highlight) and obj.document.matter_id == matter.id:
                result_item = {
                    "type": "highlight",
                    "object": obj,
                    "rank": getattr(result, "watson_rank", 0),
                    "date": obj.document.date,
                }
            elif isinstance(obj, Fact) and obj.matter_id == matter.id:
                result_item = {
                    "type": "fact",
                    "object": obj,
                    "rank": getattr(result, "watson_rank", 0),
                    "date": obj.date,
                }

            if result_item:
                results.append(result_item)

        # Apply additional filters from session
        result_type = filter_data.get("result_type", "")
        if result_type:
            results = [r for r in results if r["type"] == result_type]

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

    return {
        "results": results,
        "query": query,
        "labels": labels,
        "documents": documents,
        "filter_data": filter_data,
        "filter": filter_obj,
        "doc_count": doc_count,
        "highlight_count": highlight_count,
        "fact_count": fact_count,
    }


@login_required
def search_index(request):
    """Main search view with persistent filter panel."""
    matter, matters = get_selected_matter(request)

    context = {
        "app": "documents",
        "subapp": "search",
        "matter": matter,
        "matters": matters,
    } | get_search_data(request, matter)

    return render(request, "case/search/main.html", context)


@login_required
def search_list(request):
    """HTMX partial for full search content area."""
    matter, matters = get_selected_matter(request)

    context = {
        "app": "documents",
        "subapp": "search",
        "matter": matter,
        "matters": matters,
    } | get_search_data(request, matter)

    return render(request, "case/search/list.html", context)


@login_required
def search_results(request):
    """HTMX partial for search results only."""
    matter, _ = get_selected_matter(request)
    context = get_search_data(request, matter)
    return render(request, "case/search/results.html", context)


@login_required
def search_query(request):
    """Handle search query input via HTMX."""
    matter, _ = get_selected_matter(request)
    filter_data = request.session.get("search_filter", {})

    query = request.POST.get("query", "").strip()
    filter_data["query"] = query
    request.session["search_filter"] = filter_data

    context = get_search_data(request, matter)
    context["is_htmx"] = True
    return render(request, "case/search/results.html", context)


@login_required
def search_filter(request):
    """Filter panel update - POST saves, GET renders panel."""
    matter, _ = get_selected_matter(request)

    if request.method == "POST":
        filter_data = request.session.get("search_filter", {})
        # Update filter data with form values, preserving query
        for key, value in request.POST.items():
            if key != "csrfmiddlewaretoken":
                if value:
                    filter_data[key] = value
                else:
                    filter_data.pop(key, None)
        request.session["search_filter"] = filter_data
        return HttpResponse(status=204, headers={"HX-Trigger": "searchChanged"})

    # GET - render filter panel
    filter_data = request.session.get("search_filter", {})
    filter_obj = SearchFilter(filter_data, matter=matter)

    return render(
        request,
        "case/search/filter-panel.html",
        {"filter": filter_obj, "matter": matter, "filter_data": filter_data},
    )


@login_required
def search_filter_type(request, result_type=None):
    """Quick filter by result type."""
    filter_data = request.session.get("search_filter", {})

    if result_type:
        filter_data["result_type"] = result_type
    else:
        filter_data.pop("result_type", None)

    request.session["search_filter"] = filter_data
    return HttpResponse(status=204, headers={"HX-Trigger": "searchChanged"})


@login_required
def search_clear(request):
    """Clear search query and all filters."""
    request.session["search_filter"] = {}
    return HttpResponse(status=204, headers={"HX-Trigger": "searchChanged"})
