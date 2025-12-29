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
        order_by = filter_data.get("order_by", "")
        # Handle computed field sorting separately
        if order_by in ["unbilled", "-unbilled", "balance_due", "-balance_due"]:
            # Remove the computed field ordering from filter data for Django filter
            filter_data_copy = filter_data.copy()
            filter_data_copy.pop("order_by", None)
            filter = MatterFilter(filter_data_copy)
            matters = filter.qs
        else:
            filter = MatterFilter(filter_data)
            matters = filter.qs
    else:
        filter = MatterFilter(default_filter)
        matters = filter.qs
        order_by = ""

    request.session["matter_filter"] = filter_data if filter_data else filter.data
    request.session.modified = True

    # Convert to list to enable custom sorting for computed fields
    matters_list = list(matters)

    pagination = CustomPaginator(
        matters_list, per_page=40, request=request, session_key="matter_pagination"
    )

    # Get current order and strip leading '-' for comparison
    current_order = filter_data.get("order_by", "name") if filter_data else "name"
    current_order = current_order.lstrip("-")

    list_data["pagination"] = pagination
    list_data["session_key"] = "matter_pagination"
    list_data["trigger_key"] = "mattersChanged"
    list_data["edit"] = False
    list_data["matters"] = pagination.get_object_list()
    list_data["number_matters"] = len(matters_list)
    list_data["filter_label"] = (
        filter_data.get("filter_label", None) if filter_data else None
    )
    list_data["current_order"] = current_order

    return list_data
