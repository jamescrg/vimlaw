from apps.documents.filters import LabelsFilter
from apps.documents.models import Label
from apps.management.pagination import CustomPaginator


def get_label_data(request):
    filter_data = request.session.get("labels_filter", {})

    if filter_data:
        filter = LabelsFilter(filter_data)
        labels = filter.qs
    else:
        labels = Label.objects.all().select_related("matter").order_by("name")

    pagination = CustomPaginator(
        labels, per_page=20, request=request, session_key="labels_pagination"
    )

    context = {
        "pagination": pagination,
        "session_key": "labels_pagination",
        "trigger_key": "labelsChanged",
        "objects": pagination.get_object_list(),
    }

    return context
