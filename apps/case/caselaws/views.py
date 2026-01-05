"""
Views for case law management.

Allows users to look up case citations via CourtListener and save them to matters.
"""

import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.case.courtlistener import fetch_case_by_citation
from apps.case.models import CaseLaw, Highlight
from apps.case.views import get_matter_from_url, get_session_key, set_last_tab
from apps.matters.models import Matter

logger = logging.getLogger(__name__)


def get_accessible_matters():
    """Get all matters accessible to logged-in users."""
    return Matter.objects.filter(status="Open")


def get_caselaws_data(request, matter, matter_id):
    """Get case law data with filters applied from session."""
    filter_session_key = get_session_key("caselaws_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    case_laws = []
    if matter:
        # Get sort order
        current_order = filter_data.get("order_by", "-created_at")
        if isinstance(current_order, list):
            current_order = current_order[0] if current_order else "-created_at"

        queryset = CaseLaw.objects.filter(matter=matter).order_by(current_order)

        # Apply keyword filter if present
        keyword = filter_data.get("keyword", "")
        if isinstance(keyword, list):
            keyword = keyword[0] if keyword else ""
        if keyword:
            queryset = queryset.filter(case_name__icontains=keyword) | queryset.filter(
                citation__icontains=keyword
            )

        case_laws = queryset
    else:
        current_order = "-created_at"

    # Get keyword value
    keyword = filter_data.get("keyword", "")
    if isinstance(keyword, list):
        keyword = keyword[0] if keyword else ""

    return {
        "case_laws": case_laws,
        "current_order": current_order,
        "keyword": keyword,
    }


@login_required
def caselaws_index(request, matter_id):
    """Main case law view."""
    matter, matters = get_matter_from_url(request, matter_id)
    set_last_tab(request, matter_id, "caselaws")

    context = {
        "app": "documents",
        "subapp": "caselaws",
        "matter": matter,
        "matters": matters,
    } | get_caselaws_data(request, matter, matter_id)

    return render(request, "case/caselaws/main.html", context)


@login_required
def caselaws_list(request, matter_id):
    """HTMX partial for case law list."""
    matter, _ = get_matter_from_url(request, matter_id)

    context = {
        "matter": matter,
    } | get_caselaws_data(request, matter, matter_id)

    return render(request, "case/caselaws/list.html", context)


@login_required
def caselaws_sort(request, matter_id, order):
    """Sort case laws by a field."""
    filter_session_key = get_session_key("caselaws_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    current_order = filter_data.get("order_by", "")

    # Toggle sort direction if clicking the same column
    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    elif current_order == f"-{order}":
        new_order = order
    else:
        new_order = f"-{order}"  # Default to descending for new column

    filter_data["order_by"] = new_order
    request.session[filter_session_key] = filter_data

    return redirect("case:caselaws-list", matter_id=matter_id)


@login_required
def caselaws_add(request, matter_id):
    """Show add case law modal."""
    matter, _ = get_matter_from_url(request, matter_id)

    return render(
        request,
        "case/caselaws/add-modal.html",
        {"matter": matter},
    )


@login_required
def caselaws_lookup(request, matter_id):
    """HTMX endpoint to look up a citation."""
    matter, _ = get_matter_from_url(request, matter_id)
    citation_text = request.POST.get("citation", "").strip()

    if not citation_text:
        return render(
            request,
            "case/caselaws/lookup-result.html",
            {"error": "Please enter a citation"},
        )

    # Look up the citation
    result = fetch_case_by_citation(citation_text)

    if not result.get("found"):
        return render(
            request,
            "case/caselaws/lookup-result.html",
            {"error": result.get("error", "Citation not found")},
        )

    # Check if already saved to this matter
    existing = None
    if result.get("cluster_id"):
        existing = CaseLaw.objects.filter(
            matter=matter, cluster_id=result["cluster_id"]
        ).first()

    # Store result in session to avoid HTML escaping issues with large text
    session_key = f"caselaw_lookup_{matter_id}"
    request.session[session_key] = result

    return render(
        request,
        "case/caselaws/lookup-result.html",
        {
            "matter": matter,
            "result": result,
            "existing": existing,
            "text_preview": result.get("text", "")[:1000],
        },
    )


@login_required
@require_POST
def caselaws_save(request, matter_id):
    """Save a case law to the matter."""
    matter, _ = get_matter_from_url(request, matter_id)

    # Get data from session (stored during lookup to avoid HTML escaping issues)
    session_key = f"caselaw_lookup_{matter_id}"
    result = request.session.get(session_key, {})

    if not result:
        return HttpResponse(
            "No case data found. Please look up the citation again.", status=400
        )

    # Extract data from session result
    case_name = result.get("case_name", "")
    citation = result.get("citation", "")
    court = result.get("court", "")
    court_id = result.get("court_id", "")
    date_filed = result.get("date_filed") or None
    docket_number = result.get("docket_number", "")
    cluster_id = result.get("cluster_id")
    opinion_id = result.get("opinion_id")
    courtlistener_url = result.get("courtlistener_url", "")
    text = result.get("text", "")
    html = result.get("html", "")

    # Clean up session
    del request.session[session_key]

    # Convert IDs to int
    cluster_id = int(cluster_id) if cluster_id else None
    opinion_id = int(opinion_id) if opinion_id else None

    # Check for duplicates
    if cluster_id:
        existing = CaseLaw.objects.filter(matter=matter, cluster_id=cluster_id).first()
        if existing:
            # Already exists - redirect to view
            response = HttpResponse(status=204)
            response["HX-Redirect"] = f"/case/caselaws/{existing.id}/"
            return response

    # Create the case law
    case_law = CaseLaw.objects.create(
        matter=matter,
        case_name=case_name,
        citation=citation,
        court=court,
        court_id=court_id,
        date_filed=date_filed,
        docket_number=docket_number,
        cluster_id=cluster_id,
        opinion_id=opinion_id,
        courtlistener_url=courtlistener_url,
        text=text,
        html=html,
        created_by=request.user,
        updated_by=request.user,
    )

    logger.info("Saved case law %s to matter %s", case_law, matter)

    # Return redirect to view the case in the viewer
    response = HttpResponse(status=204)
    response["HX-Redirect"] = f"/case/caselaws/{case_law.id}/view/"
    return response


@login_required
def caselaw_edit(request, caselaw_id):
    """Edit case law notes."""
    case_law = get_object_or_404(
        CaseLaw, pk=caselaw_id, matter__in=get_accessible_matters()
    )

    if request.method == "POST":
        case_law.notes = request.POST.get("notes", "")
        case_law.updated_by = request.user
        case_law.save()

        return redirect("case:caselaws-index", matter_id=case_law.matter_id)

    return render(
        request,
        "case/caselaws/edit-modal.html",
        {"case_law": case_law},
    )


@login_required
@require_POST
def caselaw_delete(request, caselaw_id):
    """Delete a case law entry."""
    case_law = get_object_or_404(
        CaseLaw, pk=caselaw_id, matter__in=get_accessible_matters()
    )
    matter_id = case_law.matter_id

    case_law.delete()

    response = HttpResponse(status=204)
    response["HX-Redirect"] = f"/case/{matter_id}/caselaws/"
    return response


@login_required
def caselaw_importance(request, caselaw_id, value):
    """Update case law importance."""
    case_law = get_object_or_404(
        CaseLaw, pk=caselaw_id, matter__in=get_accessible_matters()
    )

    # Validate value is 1-10
    if 1 <= value <= 10:
        case_law.importance = value
        case_law.updated_by = request.user
        case_law.save(update_fields=["importance", "updated_by", "updated_at"])

    return redirect("case:caselaws-list", matter_id=case_law.matter_id)


@login_required
def caselaw_viewer(request, caselaw_id):
    """Case law viewer with highlight support."""
    case_law = get_object_or_404(
        CaseLaw, pk=caselaw_id, matter__in=get_accessible_matters()
    )
    highlights = case_law.highlights.all().order_by("char_offset", "created_at")

    initial_highlight = request.GET.get("highlight")
    try:
        initial_highlight = int(initial_highlight) if initial_highlight else None
    except (TypeError, ValueError):
        initial_highlight = None

    # Serialize highlights for JavaScript
    highlights_json = json.dumps(
        [
            {
                "id": h.id,
                "slug": h.slug,
                "text": h.text,
                "char_offset": h.char_offset,
                "color": h.color,
                "importance": h.importance,
                "citation": h.citation,
            }
            for h in highlights
        ]
    )

    return render(
        request,
        "case/caselaw-viewer.html",
        {
            "caselaw": case_law,
            "matter": case_law.matter,
            "highlights": highlights,
            "highlights_json": highlights_json,
            "initial_highlight": initial_highlight,
        },
    )


@login_required
@require_POST
def caselaw_toggle_ai(request, caselaw_id):
    """Toggle the include_in_ai flag on a case law entry."""
    case_law = get_object_or_404(
        CaseLaw, pk=caselaw_id, matter__in=get_accessible_matters()
    )

    case_law.include_in_ai = not case_law.include_in_ai
    case_law.save(update_fields=["include_in_ai", "updated_by", "updated_at"])

    # Trigger refresh of case law list
    response = HttpResponse(status=204)
    response["HX-Trigger"] = "caselawsChanged"
    return response


@login_required
@require_POST
def caselaw_add_highlight(request, caselaw_id):
    """Add highlight to case law."""
    case_law = get_object_or_404(
        CaseLaw, pk=caselaw_id, matter__in=get_accessible_matters()
    )

    slug = request.POST.get("slug", "").strip()
    if not slug:
        return JsonResponse({"error": "Slug is required"}, status=400)

    try:
        char_offset = request.POST.get("char_offset")
        char_offset = int(char_offset) if char_offset else None

        page_number = request.POST.get("page_number")
        page_number = int(page_number) if page_number else None

        highlight = Highlight.objects.create(
            caselaw=case_law,
            slug=slug,
            text=request.POST.get("text", ""),
            char_offset=char_offset,
            page_number=page_number,
            color=request.POST.get("color", "yellow"),
            importance=int(request.POST.get("importance", 5)),
            created_by=request.user,
            updated_by=request.user,
        )

        return JsonResponse(
            {
                "id": highlight.id,
                "slug": highlight.slug,
                "text": highlight.text,
                "char_offset": highlight.char_offset,
                "page_number": highlight.page_number,
                "citation": highlight.citation,
                "color": highlight.color,
                "importance": highlight.importance,
            }
        )
    except Exception as e:
        logger.exception("Error creating case law highlight")
        return JsonResponse({"error": str(e)}, status=400)
