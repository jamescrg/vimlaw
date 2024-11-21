from apps.management.pagination import CustomPaginator
from apps.matters.filter import MatterFilter


def get_matter_list(request):
    list_data = {}

    default_filter = {
        "status": "Open",
        "practice_area": "",
        "date_start": "",
        "date_end": "",
        "order_by": "name",
    }

    filter_data = request.session.get("matter_filter", {})

    if filter_data:
        filter = MatterFilter(filter_data)
        matters = filter.qs
    else:
        filter = MatterFilter(default_filter)
        matters = filter.qs

    request.session["matter_filter"] = filter.data
    request.session.modified = True

    pagination = CustomPaginator(
        matters, per_page=20, request=request, session_key="matter_pagination"
    )

    total_unbilled = 0
    for matter in matters:
        total_unbilled += matter.value["unbilled"]["net_fees_and_expenses"]

    list_data["pagination"] = pagination
    list_data["session_key"] = "matter_pagination"
    list_data["trigger_key"] = "mattersChanged"
    list_data["edit"] = False
    list_data["matters"] = pagination.get_object_list()
    list_data["number_matters"] = matters.count()
    list_data["total_unbilled"] = total_unbilled
    list_data["filter_label"] = (
        filter_data.get("filter_label", None) if filter_data else None
    )

    return list_data
