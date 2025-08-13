from apps.documents.models import Document
from apps.management.pagination import CustomPaginator


def get_document_data(request):
    documents = Document.objects.all().order_by("-uploaded_at")

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
