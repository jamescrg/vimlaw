from django.core.paginator import Paginator

from apps.settings.users.filters import UserFilter

# Default filter settings for user list
DEFAULT_USER_FILTER = {"is_active": "True"}


def get_user_list(request):
    filter_data = request.session.get("user_filter", {})

    if filter_data:
        users = UserFilter(filter_data).qs
    else:
        # Apply default filter
        users = UserFilter(DEFAULT_USER_FILTER).qs

    # Ensure consistent ordering for pagination
    if not users.query.order_by:
        users = users.order_by("username")

    page = request.GET.get("page")
    pagination = Paginator(users, 10).get_page(page)

    # Get current order and strip leading '-' for comparison
    current_order = (
        filter_data.get("order_by", "username") if filter_data else "username"
    )
    current_order = current_order.lstrip("-")

    context = {
        "subapp": "users",
        "users": pagination.object_list,
        "pagination": pagination,
        "current_order": current_order,
    }

    return context
