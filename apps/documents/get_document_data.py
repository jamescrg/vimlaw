from apps.documents.filters import DocumentsFilter
from apps.documents.models import Document, Label
from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter


def get_document_data(request):
    filter_data = request.session.get("documents_filter", {})

    if filter_data:
        filter = DocumentsFilter(filter_data)
        documents = filter.qs.select_related("matter", "uploaded_by").prefetch_related(
            "labels"
        )

        matter_id = filter_data.get("matter")
        matter_id = int(matter_id) if matter_id not in (None, "") else None
    else:
        documents = (
            Document.objects.all()
            .select_related("matter", "uploaded_by")
            .prefetch_related("labels")
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

    label_ids = (
        Document.objects.values_list("labels", flat=True)
        .distinct()
        .exclude(labels__isnull=True)
    )
    label_list = Label.objects.filter(id__in=label_ids).order_by("name")

    selected_documents = request.session.get("selected_documents", [])

    # Get selected label info
    filter_data = request.session.get("documents_filter", {})
    label_id = filter_data.get("label")
    label_id = int(label_id) if label_id not in (None, "") else None

    selected_label = None
    if label_id:
        selected_label = Label.objects.filter(id=label_id).first()

    context = {
        "pagination": pagination,
        "session_key": "documents_pagination",
        "trigger_key": "documentsChanged",
        "objects": pagination.get_object_list(),
        "matters": matter_list,
        "selected_matter": selected_matter.name if selected_matter else None,
        "labels": label_list,
        "selected_label": selected_label.name if selected_label else None,
        "selected_documents": selected_documents,
    }

    return context
