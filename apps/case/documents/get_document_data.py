from django.db.models import Count

from apps.case.models import Document, Label
from apps.case.views import get_matter_from_url, get_session_key
from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding

from .filters import FilesFilter


def get_selected_matter(request):
    """Get selected matter from session (for backwards compatibility with outlines app).

    This uses the session-based approach for apps that haven't been refactored
    to use URL-based matter context.
    """
    matters = Matter.objects.filter(status="Open").order_by("name")
    matter_id = request.session.get("last_viewed_matter")

    if matter_id:
        matter = matters.filter(id=matter_id).first()
        if matter:
            return matter, matters

    # Default to first matter
    matter = matters.first()
    if matter:
        request.session["last_viewed_matter"] = matter.id
    return matter, matters


def get_document_data(request, matter_id):
    """Get document data for a specific matter."""
    matter, matters = get_matter_from_url(request, matter_id)

    # Use matter-specific session key for filters
    filter_session_key = get_session_key("documents_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    # Always filter by the selected matter
    documents = (
        Document.objects.filter(matter=matter)
        .select_related("matter", "created_by", "proceeding")
        .prefetch_related("labels")
        .annotate(highlight_count=Count("highlights"))
        .order_by("-created_at")
    )

    # Apply additional filters if present
    if filter_data:
        filter_obj = FilesFilter(filter_data, queryset=documents, matter=matter)
        documents = filter_obj.qs

    # Use matter-specific pagination key
    pagination_session_key = get_session_key("documents_pagination", matter_id)
    pagination = CustomPaginator(
        documents, per_page=20, request=request, session_key=pagination_session_key
    )

    # Get labels for this matter's documents
    label_ids = (
        Document.objects.filter(matter=matter)
        .values_list("labels", flat=True)
        .distinct()
        .exclude(labels__isnull=True)
    )
    label_list = Label.objects.filter(id__in=label_ids).order_by("name")

    # Use matter-specific key for selected documents
    selected_session_key = get_session_key("selected_documents", matter_id)
    selected_documents = request.session.get(selected_session_key, [])

    # Check if all visible documents are selected
    visible_ids = [doc.id for doc in pagination.get_object_list()]
    all_selected = visible_ids and all(
        doc_id in selected_documents for doc_id in visible_ids
    )

    # Get proceedings for the matter (for inline proceeding dropdown)
    proceedings = Proceeding.objects.filter(matter=matter).order_by(
        "forum", "case_number"
    )

    # Get current sort order
    current_order = filter_data.get("order_by", "-created_at")
    if isinstance(current_order, list):
        current_order = current_order[0] if current_order else "-created_at"

    # Get selected category
    selected_category = filter_data.get("category")
    if isinstance(selected_category, list):
        selected_category = selected_category[0] if selected_category else None

    # Get selected keyword
    selected_keyword = filter_data.get("keyword")
    if isinstance(selected_keyword, list):
        selected_keyword = selected_keyword[0] if selected_keyword else None

    # Get importance filter value
    importance_value = filter_data.get("importance")
    if isinstance(importance_value, list):
        importance_value = importance_value[0] if importance_value else None
    importance_value = (
        int(importance_value) if importance_value not in (None, "", 0) else None
    )

    # Get selected proceeding
    selected_proceeding_id = filter_data.get("proceeding")
    if isinstance(selected_proceeding_id, list):
        selected_proceeding_id = (
            selected_proceeding_id[0] if selected_proceeding_id else None
        )
    selected_proceeding = None
    if selected_proceeding_id:
        selected_proceeding = proceedings.filter(id=selected_proceeding_id).first()

    context = {
        "matter": matter,
        "matters": matters,
        "pagination": pagination,
        "session_key": pagination_session_key,
        "trigger_key": "documentsChanged",
        "objects": pagination.get_object_list(),
        "labels": label_list,
        "selected_category": selected_category,
        "selected_keyword": selected_keyword,
        "selected_documents": selected_documents,
        "all_selected": all_selected,
        "proceedings": proceedings,
        "selected_proceeding": selected_proceeding,
        "current_order": current_order,
        "importances": list(range(1, 11)),
        "importance_value": importance_value,
        "selected_importance": (
            f"Importance {importance_value}" if importance_value else ""
        ),
    }

    return context
