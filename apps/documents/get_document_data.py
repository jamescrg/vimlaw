from apps.documents.filters import DocumentsFilter
from apps.documents.models import Document
from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter


def get_document_data(request):
    filter_data = request.session.get("documents_filter", {})

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

    matter_ids = Document.objects.values_list("matter_id", flat=True).distinct()
    matter_list = Matter.objects.filter(id__in=matter_ids).order_by("name")

    context = {
        "pagination": pagination,
        "session_key": "documents_pagination",
        "trigger_key": "documentsChanged",
        "objects": pagination.get_object_list(),
        "matters": matter_list,
        "selected_matter": selected_matter.name if selected_matter else None,
    }

    return context
