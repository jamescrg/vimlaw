from apps.documents.filters import DocumentsFilter
from apps.documents.models import Document
from apps.management.pagination import CustomPaginator


def get_document_data(request):
    filter_data = request.session.get("documents_filter", {})

    if filter_data:
        filter = DocumentsFilter(filter_data)
        documents = filter.qs
    else:
        documents = (
            Document.objects.all()
            .select_related("matter", "uploaded_by")
            .order_by("-uploaded_at")
        )

    pagination = CustomPaginator(
        documents, per_page=20, request=request, session_key="documents_pagination"
    )

    context = {
        "pagination": pagination,
        "session_key": "documents_pagination",
        "trigger_key": "documentsChanged",
        "objects": pagination.get_object_list(),
    }

    return context
