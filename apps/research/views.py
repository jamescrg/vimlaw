from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from .jurisdictions import STATES
from .models import ResearchQuery, ResearchResult
from .tasks import process_research_query


def research_permission_required(view_func):
    """Check user has research permission."""

    @login_required
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_admin or request.user.perm_research):
            return HttpResponse("Permission denied", status=403)
        return view_func(request, *args, **kwargs)

    wrapper.__name__ = view_func.__name__
    return wrapper


@research_permission_required
def research_index(request):
    queries = ResearchQuery.objects.filter(created_by=request.user)[:20]
    return render(
        request,
        "research/main.html",
        {
            "app": "research",
            "states": STATES,
            "queries": queries,
        },
    )


@research_permission_required
def research_search(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    query_text = request.POST.get("query_text", "").strip()
    state = request.POST.get("state", "")
    include_federal = request.POST.get("include_federal") == "on"

    if not query_text:
        return HttpResponse(
            '<div class="research-error">Please enter a search query.</div>'
        )

    query = ResearchQuery.objects.create(
        query_text=query_text,
        state=state,
        include_federal=include_federal,
        status="pending",
        created_by=request.user,
    )

    # Start background processing
    process_research_query(query.id)

    # Return the results shell with polling
    queries = ResearchQuery.objects.filter(created_by=request.user)[:20]
    return render(
        request,
        "research/results.html",
        {"query": query, "queries": queries},
    )


@research_permission_required
def research_results(request, query_id):
    query = get_object_or_404(ResearchQuery, pk=query_id, created_by=request.user)
    results = query.results.all()
    return render(
        request,
        "research/results.html",
        {"query": query, "results": results},
    )


@research_permission_required
def result_status(request, result_id):
    result = get_object_or_404(
        ResearchResult, pk=result_id, query__created_by=request.user
    )
    return render(request, "research/result-row.html", {"result": result})


@research_permission_required
def query_status(request, query_id):
    query = get_object_or_404(ResearchQuery, pk=query_id, created_by=request.user)
    results = query.results.all()
    return render(
        request,
        "research/status.html",
        {"query": query, "results": results},
    )


@research_permission_required
def research_detail(request, query_id):
    query = get_object_or_404(ResearchQuery, pk=query_id, created_by=request.user)
    results = query.results.all()
    queries = ResearchQuery.objects.filter(created_by=request.user)[:20]
    return render(
        request,
        "research/main.html",
        {
            "app": "research",
            "states": STATES,
            "queries": queries,
            "active_query": query,
            "results": results,
        },
    )


@research_permission_required
def research_delete(request, query_id):
    if request.method != "POST":
        return HttpResponse(status=405)

    query = get_object_or_404(ResearchQuery, pk=query_id, created_by=request.user)
    query.delete()

    queries = ResearchQuery.objects.filter(created_by=request.user)[:20]
    return render(
        request,
        "research/search-form.html",
        {
            "states": STATES,
            "queries": queries,
            "deleted": True,
        },
    )
