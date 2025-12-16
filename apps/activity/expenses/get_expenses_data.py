from datetime import datetime

from apps.accounts.models import CustomUser
from apps.activity.expenses.filter import ExpenseFilter
from apps.activity.expenses.models import ExpenseEntry
from apps.activity.expenses.summary import calculate_summary
from apps.management.pagination import CustomPaginator


def get_expenses_data(request):
    expenses = ExpenseEntry.objects.all()
    number_expenses = expenses.count()

    default_filter = {
        "date_min": "",
        "date_max": "",
        "firm": "Campbell & Brannon",
        "matter": None,
        "keyword": "",
        "comp": None,
        "entered": 0,
        "invoice": 0,
    }

    filter_data = request.session.get("expenses_filter", {})

    if filter_data:
        filter = ExpenseFilter(filter_data)

        current_date = datetime.now().date()
        filter_label = filter.data.get("filter_label", None)

        min_date = filter.data.get("date_min", None)
        max_date = filter.data.get("date_max", None)

        # If the label is 'today' make sure the dates match the current date
        if min_date and max_date:
            if (
                filter_label == "today"
                and min_date != current_date
                and max_date != current_date
            ):
                filter.data["date_min"] = str(current_date)
                filter.data["date_max"] = str(current_date)

        expenses = filter.qs
        user_id = filter_data.get("user")
        user_id = int(user_id) if user_id not in (None, "") else None
    else:
        filter = ExpenseFilter(default_filter)
        expenses = filter.qs
        user_id = None

    request.session["expenses_filter"] = filter.data
    request.session.modified = True

    summary = calculate_summary(expenses)
    users = CustomUser.objects.filter(is_active=True)

    pagination = CustomPaginator(
        expenses, per_page=10, request=request, session_key="expenses_pagination"
    )

    selected_user = None
    if user_id:
        user = users.filter(id=user_id).first()
        if user:
            selected_user = user.username.capitalize()

    # Get current order and strip leading '-' for comparison
    current_order = filter_data.get("order_by", "date") if filter_data else "date"
    current_order = current_order.lstrip("-")

    context = {
        "edit": False,
        "objects": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "expenses_pagination",
        "trigger_key": "expensesChanged",
        "number_expenses": number_expenses,
        "summary": summary,
        "users": users,
        "selected_user": selected_user,
        "user_id": user_id,
        "filter_label": filter_data.get("filter_label", None),
        "current_order": current_order,
    }

    return context
