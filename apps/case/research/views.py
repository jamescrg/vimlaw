from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from apps.case.courtlistener import (
    fetch_case_by_citation,
    fetch_cluster,
    lookup_citation,
)
from apps.case.models import CaseLaw
from apps.case.views import get_matter_from_url, set_last_tab

from .courtlistener import count_forward_citations
from .jurisdictions import STATES
from .models import CitationVerification, ResearchQuery, ResearchResult
from .tasks import (
    assess_single_citation,
    process_research_query,
    refine_research_query,
    review_more_citations,
    review_result,
    sanitize_query,
)


def get_research_data(request, matter, matter_id):
    """Get research data for the case tab."""
    return {
        "states": STATES,
    }


@login_required
def research_index(request, matter_id):
    """Main research view (full page load)."""
    matter, matters = get_matter_from_url(request, matter_id)
    set_last_tab(request, matter_id, "research")

    context = {
        "app": "matters",
        "subapp": "research",
        "matter": matter,
        "matters": matters,
        "research_tab": "search",
    } | get_research_data(request, matter, matter_id)

    return render(request, "case/research/main.html", context)


@login_required
def research_list(request, matter_id):
    """HTMX partial for research tab content."""
    matter, _ = get_matter_from_url(request, matter_id)

    context = {
        "matter": matter,
        "research_tab": "search",
    } | get_research_data(request, matter, matter_id)

    return render(request, "case/research/list.html", context)


# ── Internal sub-tab views ────────────────────────────────────────────────


@login_required
def research_caselaws_tab(request, matter_id):
    """HTMX partial for the Case Law sub-tab content."""
    from apps.case.caselaws.views import get_caselaws_data

    matter, _ = get_matter_from_url(request, matter_id)

    context = {
        "matter": matter,
        "research_tab": "caselaws",
    } | get_caselaws_data(request, matter, matter_id)

    return render(request, "case/research/list.html", context)


@login_required
def research_search_tab(request, matter_id):
    """HTMX partial for the Search sub-tab content."""
    matter, _ = get_matter_from_url(request, matter_id)

    context = {
        "matter": matter,
        "research_tab": "search",
        "states": STATES,
    }

    return render(request, "case/research/list.html", context)


@login_required
def research_history_tab(request, matter_id):
    """HTMX partial for the History sub-tab content."""
    matter, _ = get_matter_from_url(request, matter_id)

    queries = ResearchQuery.objects.filter(matter=matter, created_by=request.user)[:50]

    context = {
        "matter": matter,
        "research_tab": "history",
        "queries": queries,
    }

    return render(request, "case/research/list.html", context)


@login_required
def research_review_tab(request, matter_id):
    """HTMX partial for the Review sub-tab content."""
    matter, _ = get_matter_from_url(request, matter_id)

    result_id = request.GET.get("result")
    context = {
        "matter": matter,
        "research_tab": "review",
    }

    if result_id:
        result = get_object_or_404(
            ResearchResult,
            pk=result_id,
            query__matter=matter,
            query__created_by=request.user,
        )
        context["result"] = result
    else:
        reviewed_results = ResearchResult.objects.filter(
            query__matter=matter,
            query__created_by=request.user,
            verify_status="complete",
        ).select_related("query")
        context["reviewed_results"] = reviewed_results

    return render(request, "case/research/list.html", context)


# ── Search flow ───────────────────────────────────────────────────────────


@login_required
def research_search(request, matter_id):
    """POST: create a new research query."""
    if request.method != "POST":
        return HttpResponse(status=405)

    matter, _ = get_matter_from_url(request, matter_id)

    query_text = request.POST.get("query_text", "").strip()
    state = request.POST.get("state", "")
    include_federal = request.POST.get("include_federal") == "on"

    if not query_text:
        return HttpResponse(
            '<div class="research-error">Please enter a search query.</div>'
        )

    query = ResearchQuery.objects.create(
        matter=matter,
        query_text=query_text,
        state=state,
        include_federal=include_federal,
        status="pending",
        created_by=request.user,
    )

    refine_research_query(query.id)

    return render(
        request,
        "case/research/results.html",
        {"query": query, "matter": matter},
    )


@login_required
def research_results(request, matter_id, query_id):
    """View results for a specific query."""
    matter, _ = get_matter_from_url(request, matter_id)
    query = get_object_or_404(
        ResearchQuery, pk=query_id, matter=matter, created_by=request.user
    )
    results = query.results.all()
    return render(
        request,
        "case/research/results.html",
        {"query": query, "results": results, "matter": matter},
    )


@login_required
def research_detail(request, matter_id, query_id):
    """View a specific query with search form and results."""
    matter, matters = get_matter_from_url(request, matter_id)
    set_last_tab(request, matter_id, "research")
    query = get_object_or_404(
        ResearchQuery, pk=query_id, matter=matter, created_by=request.user
    )
    results = query.results.all()
    return render(
        request,
        "case/research/main.html",
        {
            "app": "matters",
            "subapp": "research",
            "matter": matter,
            "matters": matters,
            "research_tab": "search",
            "states": STATES,
            "active_query": query,
            "results": results,
        },
    )


@login_required
def research_confirm(request, matter_id, query_id):
    """POST: confirm structured query and start search."""
    if request.method != "POST":
        return HttpResponse(status=405)

    matter, _ = get_matter_from_url(request, matter_id)
    query = get_object_or_404(
        ResearchQuery, pk=query_id, matter=matter, created_by=request.user
    )

    structured_query = request.POST.get("structured_query", "").strip()
    if structured_query:
        query.structured_query = sanitize_query(structured_query)
        query.save(update_fields=["structured_query"])

    query.status = "searching"
    query.save(update_fields=["status"])

    process_research_query(query.id)

    results = query.results.all()
    return render(
        request,
        "case/research/results.html",
        {"query": query, "results": results, "matter": matter},
    )


@login_required
def research_delete(request, matter_id, query_id):
    """POST: delete a research query."""
    if request.method != "POST":
        return HttpResponse(status=405)

    matter, _ = get_matter_from_url(request, matter_id)
    query = get_object_or_404(
        ResearchQuery, pk=query_id, matter=matter, created_by=request.user
    )
    query.delete()

    response = HttpResponse(status=200)
    response["HX-Redirect"] = reverse("case:research-index", args=[matter_id])
    return response


# ── Polling endpoints (object-specific, no matter_id needed) ──────────────


@login_required
def query_status(request, query_id):
    """Poll for query processing status."""
    query = get_object_or_404(ResearchQuery, pk=query_id, created_by=request.user)
    results = query.results.all()
    return render(
        request,
        "case/research/results.html",
        {"query": query, "results": results, "matter": query.matter},
    )


@login_required
def result_status(request, result_id):
    """Poll for individual result status."""
    result = get_object_or_404(
        ResearchResult, pk=result_id, query__created_by=request.user
    )
    return render(
        request,
        "case/research/result-row.html",
        {"result": result, "matter": result.query.matter},
    )


# ── Review flow (object-specific) ────────────────────────────────────────


@login_required
def research_review(request, result_id):
    """POST: start review from a search result."""
    if request.method != "POST":
        return HttpResponse(status=405)

    result = get_object_or_404(
        ResearchResult, pk=result_id, query__created_by=request.user
    )
    matter = result.query.matter

    result.verify_status = "verifying"
    result.save(update_fields=["verify_status"])
    review_result(result.id)

    context = {
        "matter": matter,
        "research_tab": "review",
        "result": result,
    }
    return render(request, "case/research/list.html", context)


@login_required
def research_review_lookup(request, matter_id):
    """POST: look up a citation and start review."""
    if request.method != "POST":
        return HttpResponse(status=405)

    matter, _ = get_matter_from_url(request, matter_id)

    citation_text = request.POST.get("citation", "").strip()
    if not citation_text:
        context = {
            "matter": matter,
            "research_tab": "review",
        }
        return render(request, "case/research/list.html", context)

    lookup = lookup_citation(citation_text)
    if not lookup.found:
        context = {
            "matter": matter,
            "research_tab": "review",
            "lookup_error": lookup.error or "Citation not found.",
            "lookup_citation": citation_text,
        }
        return render(request, "case/research/list.html", context)

    fwd_count = None
    cluster = fetch_cluster(lookup.cluster_id)
    if cluster:
        sub_opinions = cluster.get("sub_opinions", [])
        if sub_opinions:
            try:
                opinion_id = int(sub_opinions[0].rstrip("/").split("/")[-1])
                fwd_count = count_forward_citations(opinion_id)
            except (ValueError, IndexError):
                pass

    citation_str = lookup.citation
    if lookup.date_filed:
        citation_str = f"{citation_str} ({lookup.date_filed.year})"

    query = ResearchQuery.objects.create(
        matter=matter,
        query_text=citation_text,
        status="complete",
        created_by=request.user,
    )

    result = ResearchResult.objects.create(
        query=query,
        position=1,
        case_name=lookup.case_name,
        citation=citation_str,
        court=lookup.court,
        date_filed=str(lookup.date_filed) if lookup.date_filed else "",
        cluster_id=lookup.cluster_id,
        courtlistener_url=(
            f"https://www.courtlistener.com{lookup.absolute_url}"
            if lookup.absolute_url
            else ""
        ),
        forward_citation_count=fwd_count,
        relevance="high",
        verify_status="verifying",
    )

    review_result(result.id)

    return HttpResponseRedirect(
        f"{reverse('case:research-review-tab', args=[matter_id])}?result={result.id}"
    )


@login_required
def research_review_status(request, result_id):
    """Poll for review status."""
    result = get_object_or_404(
        ResearchResult, pk=result_id, query__created_by=request.user
    )
    return render(
        request,
        "case/research/review-content.html",
        {"result": result, "matter": result.query.matter},
    )


@login_required
def research_review_more(request, result_id):
    """POST: evaluate more unevaluated forward citations."""
    if request.method != "POST":
        return HttpResponse(status=405)

    result = get_object_or_404(
        ResearchResult, pk=result_id, query__created_by=request.user
    )

    result.verify_status = "verifying"
    result.save(update_fields=["verify_status"])
    review_more_citations(result.id)

    return render(
        request,
        "case/research/review-content.html",
        {"result": result, "matter": result.query.matter},
    )


@login_required
def research_assess_citation(request, verification_id):
    """POST: assess a single forward citation."""
    if request.method != "POST":
        return HttpResponse(status=405)

    verification = get_object_or_404(
        CitationVerification,
        pk=verification_id,
        result__query__created_by=request.user,
    )

    assess_single_citation(verification.id)

    return render(
        request,
        "case/research/citation-item.html",
        {"v": verification, "assessing": True},
    )


@login_required
def research_citation_status(request, verification_id):
    """Poll for a single citation assessment status."""
    verification = get_object_or_404(
        CitationVerification,
        pk=verification_id,
        result__query__created_by=request.user,
    )
    return render(
        request,
        "case/research/citation-item.html",
        {"v": verification, "assessing": not verification.summary},
    )


# ── Save to Case Law ─────────────────────────────────────────────────────


@login_required
def research_save_to_caselaws(request, result_id):
    """POST: save a research result to the matter's case law library."""
    if request.method != "POST":
        return HttpResponse(status=405)

    result = get_object_or_404(
        ResearchResult, pk=result_id, query__created_by=request.user
    )
    matter = result.query.matter

    # Check for duplicate
    if result.cluster_id:
        existing = CaseLaw.objects.filter(
            matter=matter, cluster_id=result.cluster_id
        ).first()
        if existing:
            return render(
                request,
                "case/research/result-row.html",
                {"result": result, "matter": matter, "saved_to_caselaws": True},
            )

    # Fetch full case data from CourtListener
    case_data = fetch_case_by_citation(result.citation or result.case_name)

    if not case_data.get("found"):
        return render(
            request,
            "case/research/result-row.html",
            {
                "result": result,
                "matter": matter,
                "save_error": "Could not fetch case data from CourtListener.",
            },
        )

    CaseLaw.objects.create(
        matter=matter,
        case_name=case_data.get("case_name", result.case_name),
        citation=case_data.get("citation", result.citation),
        court=case_data.get("court", result.court),
        court_id=case_data.get("court_id", ""),
        date_filed=case_data.get("date_filed"),
        docket_number=case_data.get("docket_number", ""),
        cluster_id=case_data.get("cluster_id", result.cluster_id),
        opinion_id=case_data.get("opinion_id"),
        courtlistener_url=case_data.get("courtlistener_url", result.courtlistener_url),
        text=case_data.get("text", ""),
        html=case_data.get("html", ""),
        created_by=request.user,
        updated_by=request.user,
    )

    return render(
        request,
        "case/research/result-row.html",
        {"result": result, "matter": matter, "saved_to_caselaws": True},
    )
