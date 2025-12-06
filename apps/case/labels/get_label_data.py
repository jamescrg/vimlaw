from apps.case.documents.get_document_data import get_selected_matter
from apps.case.models import Label


def get_label_data(request):
    matter, matters = get_selected_matter(request)

    # Global labels (no matter assigned)
    global_labels = Label.objects.filter(matter=None).order_by("name")

    # Matter-specific labels (if matter selected)
    if matter:
        matter_labels = Label.objects.filter(matter=matter).order_by("name")
    else:
        matter_labels = Label.objects.none()

    context = {
        "matter": matter,
        "matters": matters,
        "global_labels": global_labels,
        "matter_labels": matter_labels,
        "trigger_key": "labelsChanged",
    }

    return context
