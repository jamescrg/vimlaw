from apps.documents.filters import DocumentsFilter
from apps.documents.models import Document
from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter


def get_document_data(request):
    filter_data = request.session.get("documents_filter", {})

    matter_ids = Document.objects.values_list("matter_id", flat=True).distinct()
    matter_list = Matter.objects.filter(id__in=matter_ids).order_by("name")

    # If no matter is selected, automatically select the first one
    if not filter_data or not filter_data.get("matter"):
        first_matter = matter_list.first()

        if first_matter:
            if not filter_data:
                filter_data = {}

            filter_data["matter"] = first_matter.id
            request.session["documents_filter"] = filter_data

    if filter_data:
        filter = DocumentsFilter(filter_data)
        documents = filter.qs

        matter_id = filter_data.get("matter")
        matter_id = int(matter_id) if matter_id not in (None, "") else None
    else:
        documents = (
            Document.objects.all()
            .select_related("matter", "uploaded_by")
            .order_by("-uploaded_at")
        )

        matter_id = None

    pagination = CustomPaginator(
        documents, per_page=20, request=request, session_key="documents_pagination"
    )

    selected_matter = None
    if matter_id:
        selected_matter = Matter.objects.filter(id=matter_id).first()

    context = {
        "pagination": pagination,
        "session_key": "documents_pagination",
        "trigger_key": "documentsChanged",
        "objects": pagination.get_object_list(),
        "matters": matter_list,
        "selected_matter": selected_matter.name if selected_matter else None,
        "matter_id": matter_id,
    }

    return context
