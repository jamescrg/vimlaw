from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.activity.expenses.filter import ExpenseFilter
from apps.activity.expenses.models import ExpenseEntry
from apps.activity.expenses.summary import calculate_summary
from apps.activity.presets import activity_date_filters
from apps.management.pagination import CustomPaginator
from apps.management.selection import (
    all_visible_selected,
    get_selected_ids,
    get_session_key,
)
from apps.matters.models import Matter
from apps.tasks.services import refresh_date_preset
from apps.tasks.tasks import get_user_chips


def get_expenses_data(request):
    expenses = ExpenseEntry.objects.select_related("matter").all()

    # Filter expenses for users without perm_all_matters
    if not request.user.is_admin and not request.user.perm_all_matters:
        expenses = expenses.filter(matter__in=request.user.assigned_matters.all())

    number_expenses = expenses.count()

    default_filter = {
        "date_min": "",
        "date_max": "",
        "matter": None,
        "keyword": "",
        "comp": None,
        "entered": 0,
        "invoice": 0,
        "order_by": "-date",
    }

    filter_data = request.session.get("expenses_filter", {})

    # Clean up legacy sessions that stored the "All Users" sentinel (0).
    if filter_data.get("user") in (0, "0"):
        filter_data.pop("user", None)

    if filter_data:
        # Semantic date presets: re-derive the stored window from today so a
        # session's "Today" / "This Week" never goes stale (same mechanism as
        # the tasks tab; activity vocabulary from apps.activity.presets).
        today = timezone.localdate()
        filter_data = refresh_date_preset(
            filter_data, today, presets=activity_date_filters(today)
        )
        filter = ExpenseFilter(filter_data, queryset=expenses)

        expenses = filter.qs
        user_id = filter_data.get("user")
        user_id = int(user_id) if user_id not in (None, "") else None
    else:
        filter = ExpenseFilter(default_filter, queryset=expenses)
        expenses = filter.qs
        user_id = None

    request.session["expenses_filter"] = filter.data
    request.session.modified = True

    summary = calculate_summary(expenses)
    users = CustomUser.objects.filter(is_active=True).order_by("username")

    pagination = CustomPaginator(
        expenses, per_page=10, request=request, session_key="expenses_pagination"
    )

    selected_user = None
    if user_id:
        user = users.filter(id=user_id).first()
        if user:
            selected_user = user.username.capitalize()

    # Get current order and strip leading '-' for comparison
    current_order = filter_data.get("order_by", "-date") if filter_data else "-date"
    current_order = current_order.lstrip("-")

    # Get selection data
    session_key = get_session_key("selected_expenses")
    selected_expenses = get_selected_ids(request, session_key)

    visible_ids = [expense.id for expense in pagination.get_object_list()]
    all_selected = all_visible_selected(selected_expenses, visible_ids)

    # Filter button is the superset signal for the modal-only dimensions.
    # Date and user have dedicated dropdowns that show their own active state,
    # so they're intentionally excluded here. entered/invoice get folded in
    # only when they're NOT already conveyed by the "Unbilled" date preset.
    custom_filter_active = bool(filter_data) and any(
        [
            filter_data.get("matter") not in (None, ""),
            filter_data.get("description", "") != "",
            filter_data.get("comp") not in (None, ""),
            filter_data.get("filter_label") != "unbilled"
            and filter_data.get("entered") not in (None, ""),
            filter_data.get("filter_label") != "unbilled"
            and filter_data.get("invoice") not in (None, ""),
        ]
    )

    context = {
        "edit": False,
        "objects": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "expenses_pagination",
        "trigger_key": "expensesChanged",
        "number_expenses": number_expenses,
        "summary": summary,
        "users": users,
        "user_chips": get_user_chips(request, users, user_id),
        "chip_pinned_ids": request.user.task_user_chips or [],
        "selected_user": selected_user,
        "user_id": user_id,
        "filter_label": filter_data.get("filter_label", None),
        "custom_filter_active": custom_filter_active,
        "current_order": current_order,
        "selected_expenses": selected_expenses,
        "all_selected": all_selected,
        "matters": Matter.objects.filter(
            status__in=["Pending", "Open", "Complete"]
        ).order_by("name"),
    }

    return context
