from apps.invoicing.credits.filters import CreditsFilter
from apps.invoicing.credits.models import Credit
from apps.management.pagination import CustomPaginator


def get_credits_data(request):
    filter_data = request.session.get("credits_filter", {})

    if filter_data:
        filter = CreditsFilter(filter_data)
        credits = filter.qs
        pass
    else:
        credits = Credit.objects.all().select_related("matter").order_by("-date", "-id")

    pagination = CustomPaginator(
        credits, per_page=10, request=request, session_key="credits_pagination"
    )

    # Get current order and strip leading '-' for comparison
    current_order = filter_data.get("order_by", "date") if filter_data else "date"
    current_order = current_order.lstrip("-")

    filter_active = bool(
        filter_data
        and any(
            v for k, v in filter_data.items() if k != "order_by" and v not in (None, "")
        )
    )

    context = {
        "pagination": pagination,
        "session_key": "credits_pagination",
        "trigger_key": "creditsChanged",
        "objects": pagination.get_object_list(),
        "current_order": current_order,
        "filter_active": filter_active,
    }

    return context
