import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.case.models import Document, Highlight
from apps.case.views import get_matter_from_url, get_session_key, set_last_tab
from apps.management.pagination import CustomPaginator

from .filters import HighlightsFilter
from .forms import HighlightForm


def get_highlights_data(request, matter, matter_id):
    """Get highlights data with filters applied from session."""
    filter_session_key = get_session_key("highlights_filter", matter_id)
    pagination_session_key = get_session_key("highlights_pagination", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    highlights = []
    documents = []
    selected_document = None

    # Extract values from filter_data (handles both list and string formats)
    def get_filter_value(key):
        val = filter_data.get(key, "")
        return val[0] if isinstance(val, list) else val

    keyword = get_filter_value("keyword")
    order_by = get_filter_value("order_by")
    document_id = get_filter_value("document")

    if matter:
        highlights = Highlight.objects.filter(document__matter=matter).select_related(
            "document", "document__matter", "created_by"
        )
        documents = Document.objects.filter(matter=matter).order_by("name")

        # Apply filters using HighlightsFilter
        highlight_filter = HighlightsFilter(
            filter_data, queryset=highlights, matter=matter
        )
        highlights = highlight_filter.qs

        # Get selected document for template
        if document_id:
            selected_document = documents.filter(id=document_id).first()

        # Handle custom ordering with secondary sorts
        if order_by == "date":
            highlights = highlights.order_by("document__date", "slug", "page_number")
        elif order_by == "-date":
            highlights = highlights.order_by("-document__date", "slug", "page_number")
        elif order_by == "slug":
            highlights = highlights.order_by("slug", "document__date", "page_number")
        elif order_by == "-slug":
            highlights = highlights.order_by("-slug", "document__date", "page_number")
        elif order_by == "created":
            highlights = highlights.order_by("created_at", "slug")
        elif order_by == "-created":
            highlights = highlights.order_by("-created_at", "slug")
        elif order_by == "importance":
            highlights = highlights.order_by("importance", "document__date", "slug")
        elif order_by == "-importance":
            highlights = highlights.order_by("-importance", "document__date", "slug")
        elif not order_by:
            # Default: order by created date (oldest to newest)
            highlights = highlights.order_by("created_at", "slug")

    # Determine current_order for template (strip leading '-' for base field)
    current_order = order_by if order_by else "created"

    # Get importance filter value
    importance_value = get_filter_value("importance")
    importance_value = (
        int(importance_value) if importance_value not in (None, "", 0) else None
    )

    # Paginate highlights
    pagination = CustomPaginator(
        highlights, per_page=10, request=request, session_key=pagination_session_key
    )
    highlights = pagination.get_object_list()

    return {
        "highlights": highlights,
        "pagination": pagination,
        "session_key": pagination_session_key,
        "trigger_key": "highlightsChanged",
        "documents": documents,
        "selected_document": selected_document,
        "keyword": keyword,
        "order_by": order_by,
        "current_order": current_order,
        "importance_choices": range(1, 11),
        "importances": list(range(1, 11)),
        "importance_value": importance_value,
        "selected_importance": (
            f"Importance {importance_value}" if importance_value else ""
        ),
    }


@login_required
def highlights_index(request, matter_id):
    """Main highlights list view."""
    matter, matters = get_matter_from_url(request, matter_id)
    set_last_tab(request, matter_id, "highlights")

    context = {
        "app": "documents",
        "subapp": "highlights",
        "matter": matter,
        "matters": matters,
    } | get_highlights_data(request, matter, matter_id)

    return render(request, "case/highlights/main.html", context)


@login_required
def highlights_list(request, matter_id):
    """HTMX partial for highlights list."""
    matter, matters = get_matter_from_url(request, matter_id)

    context = {
        "app": "documents",
        "subapp": "highlights",
        "matter": matter,
        "matters": matters,
    } | get_highlights_data(request, matter, matter_id)

    return render(request, "case/highlights/list.html", context)


@login_required
def highlights_filter_document(request, matter_id, document_id=None):
    """Filter highlights by document (inline dropdown)."""
    filter_session_key = get_session_key("highlights_filter", matter_id)
    pagination_session_key = get_session_key("highlights_pagination", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    if document_id:
        filter_data["document"] = document_id  # Store as int
    else:
        filter_data["document"] = ""  # Empty string for "All"

    request.session[filter_session_key] = filter_data
    request.session[pagination_session_key] = 1  # Reset to page 1

    return HttpResponse(status=204, headers={"HX-Trigger": "highlightsChanged"})


@login_required
def highlights_for_document(request, document_id):
    """Set document filter and redirect to highlights page."""
    document = get_object_or_404(Document, id=document_id)
    matter_id = document.matter_id

    filter_session_key = get_session_key("highlights_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    filter_data["document"] = document_id
    request.session[filter_session_key] = filter_data

    return redirect("case:highlights-index", matter_id=matter_id)


@login_required
def highlights_filter_keyword(request, matter_id):
    """Filter highlights by keyword (inline search)."""
    matter, _ = get_matter_from_url(request, matter_id)
    filter_session_key = get_session_key("highlights_filter", matter_id)
    pagination_session_key = get_session_key("highlights_pagination", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    keyword = request.POST.get("keyword", "").strip()

    filter_data["keyword"] = keyword  # Store as simple string

    request.session[filter_session_key] = filter_data
    request.session[pagination_session_key] = 1  # Reset to page 1

    # Render just the cards partial (for search input updates)
    context = {"matter": matter} | get_highlights_data(request, matter, matter_id)
    return render(request, "case/highlights/cards.html", context)


@login_required
def highlights_filter_importance(request, matter_id, importance_value):
    """Filter highlights by importance level."""
    filter_session_key = get_session_key("highlights_filter", matter_id)
    pagination_session_key = get_session_key("highlights_pagination", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    # Set to empty string when 0 (All) is selected, otherwise use the value
    filter_data["importance"] = "" if importance_value == 0 else importance_value

    request.session[filter_session_key] = filter_data
    request.session[pagination_session_key] = 1  # Reset to page 1

    return redirect("case:highlights-list", matter_id=matter_id)


@login_required
def highlights_filter(request, matter_id):
    """Filter modal for highlights - GET shows modal, POST saves to session."""
    matter, matters = get_matter_from_url(request, matter_id)
    filter_session_key = get_session_key("highlights_filter", matter_id)
    pagination_session_key = get_session_key("highlights_pagination", matter_id)

    if request.method == "POST":
        # Store POST values directly (matching tasks pattern)
        filter_data = {
            key: value
            for key, value in request.POST.items()
            if key != "csrfmiddlewaretoken"
        }
        request.session[filter_session_key] = filter_data
        request.session[pagination_session_key] = 1  # Reset to page 1
        return HttpResponse(status=204, headers={"HX-Trigger": "highlightsChanged"})

    # GET - show filter modal
    filter_data = request.session.get(filter_session_key, {})

    queryset = (
        Highlight.objects.filter(document__matter=matter)
        if matter
        else Highlight.objects.none()
    )

    filter_obj = HighlightsFilter(filter_data, queryset=queryset, matter=matter)

    context = {
        "filter": filter_obj,
        "matter": matter,
    }

    return render(request, "case/highlights/filter.html", context)


@login_required
def highlights_filter_sort(request, matter_id, order):
    """Sort highlights by field, toggling asc/desc."""
    filter_session_key = get_session_key("highlights_filter", matter_id)
    pagination_session_key = get_session_key("highlights_pagination", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    current_order = filter_data.get("order_by", "")

    # Toggle direction if same field
    if current_order == order:
        filter_data["order_by"] = f"-{order}"
    elif current_order == f"-{order}":
        filter_data["order_by"] = order
    else:
        filter_data["order_by"] = order

    request.session[filter_session_key] = filter_data
    request.session[pagination_session_key] = 1  # Reset to page 1

    return HttpResponse(status=204, headers={"HX-Trigger": "highlightsChanged"})


@login_required
def highlights_filter_default(request, matter_id):
    """Reset highlights filter to defaults."""
    filter_session_key = get_session_key("highlights_filter", matter_id)
    request.session[filter_session_key] = {
        "document": "",
        "keyword": "",
        "order_by": "created",
    }
    return redirect("case:highlights-index", matter_id=matter_id)


@login_required
def highlight_importance(request, highlight_id, importance):
    """Set highlight importance."""
    highlight = get_object_or_404(Highlight, id=highlight_id)
    highlight.importance = importance
    highlight.save()
    return redirect("case:highlights-list", matter_id=highlight.document.matter_id)


@login_required
@require_POST
def add_highlight(request, document_id):
    """Create a new highlight."""
    document = get_object_or_404(Document, id=document_id)

    slug = request.POST.get("slug", "").strip()
    if not slug:
        return JsonResponse({"error": "Slug is required"}, status=400)

    try:
        coordinates = json.loads(request.POST.get("coordinates", "{}"))

        paragraph_number = request.POST.get("paragraph_number", "").strip() or None

        highlight = Highlight.objects.create(
            document=document,
            slug=slug,
            text=request.POST.get("text"),
            page_number=int(request.POST.get("page_number")),
            paragraph_number=paragraph_number,
            coordinates=coordinates,
            color=request.POST.get("color", "yellow"),
            importance=5,
            created_by=request.user,
        )

        return JsonResponse(
            {
                "id": highlight.id,
                "slug": highlight.slug,
                "text": highlight.text,
                "page_number": highlight.page_number,
                "paragraph_number": highlight.paragraph_number,
                "citation": highlight.citation,
                "coordinates": highlight.coordinates,
                "color": highlight.color,
                "importance": highlight.importance,
            }
        )
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
def delete_highlight(request, highlight_id):
    """Delete a highlight."""
    highlight = get_object_or_404(Highlight, id=highlight_id)

    # Check permission (creator or allow all authenticated users for now)
    highlight.delete()

    # Return 204 with trigger for HTMX, JSON for JS (viewer context)
    if request.headers.get("HX-Request"):
        return HttpResponse(status=204, headers={"HX-Trigger": "highlightsChanged"})
    return JsonResponse({"success": True})


@login_required
def highlight_detail(request, highlight_id):
    """Display highlight details in a modal."""
    highlight = get_object_or_404(
        Highlight.objects.select_related("document").prefetch_related("labels"),
        id=highlight_id,
    )
    return render(
        request,
        "case/highlights/detail.html",
        {"highlight": highlight, "matter": highlight.document.matter},
    )


@login_required
def edit_highlight(request, highlight_id):
    """Edit a highlight's slug, color, importance, and text."""
    highlight = get_object_or_404(Highlight, id=highlight_id)
    is_viewer_context = request.GET.get("context") == "viewer"

    if request.method == "POST":
        form = HighlightForm(request.POST, instance=highlight)
        if form.is_valid():
            form.save()
            # Return JSON for viewer context, HX-Trigger for highlights list
            if is_viewer_context:
                return JsonResponse(
                    {
                        "id": highlight.id,
                        "slug": highlight.slug,
                        "color": highlight.color,
                        "importance": highlight.importance,
                        "text": highlight.text,
                        "citation": highlight.citation,
                    }
                )
            return HttpResponse(
                status=204,
                headers={"HX-Trigger": "highlightsChanged"},
            )
    else:
        form = HighlightForm(instance=highlight)

    return render(
        request,
        "case/highlights/edit.html",
        {
            "highlight": highlight,
            "form": form,
            "matter": highlight.document.matter,
            "is_viewer_context": is_viewer_context,
        },
    )


@login_required
def highlight_link(request, highlight_id):
    """Redirect to viewer at specific highlight location."""
    highlight = get_object_or_404(Highlight, id=highlight_id)

    from django.urls import reverse

    viewer_url = reverse("case:viewer", args=[highlight.document_id])
    return redirect(
        f"{viewer_url}?page={highlight.page_number}&highlight={highlight.id}"
    )
