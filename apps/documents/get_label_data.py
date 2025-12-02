from django.db.models import Q

from apps.documents.filters import LabelsFilter
from apps.documents.get_document_data import get_selected_matter
from apps.documents.models import Label
from apps.management.pagination import CustomPaginator


def get_label_data(request):
    matter, matters = get_selected_matter(request)

    filter_data = request.session.get("labels_filter", {})

    # Show global labels + matter-specific labels (if matter selected)
    if matter:
        labels = Label.objects.filter(Q(matter=None) | Q(matter=matter))
    else:
        # No matter selected - show only global labels
        labels = Label.objects.filter(matter=None)

    # Order: global labels first, then matter labels, alphabetically within each
    labels = labels.order_by("matter", "name")

    if filter_data:
        filter_obj = LabelsFilter(filter_data, queryset=labels)
        labels = filter_obj.qs

    pagination = CustomPaginator(
        labels, per_page=20, request=request, session_key="labels_pagination"
    )

    context = {
        "matter": matter,
        "matters": matters,
        "pagination": pagination,
        "session_key": "labels_pagination",
        "trigger_key": "labelsChanged",
        "objects": pagination.get_object_list(),
    }

    return context
