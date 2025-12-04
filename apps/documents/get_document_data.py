from django.db.models import Count

from apps.documents.filters import FilesFilter
from apps.documents.models import Document, Label
from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding


def get_selected_matter(request):
    """Get the currently selected matter from session, or default to first available."""
    matter_id = request.session.get("documents_selected_matter")

    # Get all open matters for the dropdown
    matters = Matter.objects.filter(status="Open").order_by("name")

    if matter_id:
        matter = matters.filter(id=matter_id).first()
        if matter:
            return matter, matters

    # Default to first matter if none selected
    matter = matters.first()
    if matter:
        request.session["documents_selected_matter"] = matter.id

    return matter, matters


def get_document_data(request):
    matter, matters = get_selected_matter(request)

    if not matter:
        return {
            "matter": None,
            "matters": matters,
            "objects": [],
            "pagination": None,
            "labels": [],
            "selected_documents": [],
        }

    filter_data = request.session.get("documents_filter", {})

    # Always filter by the selected matter
    documents = (
        Document.objects.filter(matter=matter)
        .select_related("matter", "uploaded_by", "proceeding")
        .prefetch_related("labels")
        .annotate(highlight_count=Count("highlights"))
        .order_by("-uploaded_at")
    )

    # Apply additional filters if present
    if filter_data:
        filter_obj = FilesFilter(filter_data, queryset=documents, matter=matter)
        documents = filter_obj.qs

    pagination = CustomPaginator(
        documents, per_page=20, request=request, session_key="documents_pagination"
    )

    # Get labels for this matter's documents
    label_ids = (
        Document.objects.filter(matter=matter)
        .values_list("labels", flat=True)
        .distinct()
        .exclude(labels__isnull=True)
    )
    label_list = Label.objects.filter(id__in=label_ids).order_by("name")

    selected_documents = request.session.get("selected_documents", [])

    # Get proceedings for the matter (for inline proceeding dropdown)
    proceedings = Proceeding.objects.filter(matter=matter).order_by(
        "forum", "case_number"
    )

    # Get current sort order
    current_order = filter_data.get("order_by", "-uploaded_at")
    if isinstance(current_order, list):
        current_order = current_order[0] if current_order else "-uploaded_at"

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

    context = {
        "matter": matter,
        "matters": matters,
        "pagination": pagination,
        "session_key": "documents_pagination",
        "trigger_key": "filesChanged",
        "objects": pagination.get_object_list(),
        "labels": label_list,
        "selected_category": selected_category,
        "selected_keyword": selected_keyword,
        "selected_documents": selected_documents,
        "proceedings": proceedings,
        "current_order": current_order,
        "importances": list(range(1, 11)),
        "importance_value": importance_value,
        "selected_importance": (
            f"Importance {importance_value}" if importance_value else ""
        ),
    }

    return context
