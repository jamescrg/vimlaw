from django.core.paginator import Paginator

from apps.accounts.models import CustomUser
from apps.settings.users.filters import UserFilter


def get_user_list(request):
    filter_data = request.session.get("user_filter", None)

    if filter_data:
        users = UserFilter(filter_data).qs
    else:
        users = CustomUser.objects.all().order_by("username")

    page = request.GET.get("page")
    pagination = Paginator(users, 10).get_page(page)

    context = {
        "subapp": "users",
        "users": pagination.object_list,
        "pagination": pagination,
    }

    return context
