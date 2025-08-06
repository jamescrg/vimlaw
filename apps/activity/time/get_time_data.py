from datetime import datetime

from apps.accounts.models import CustomUser
from apps.activity.time.filter import TimeEntryFilter
from apps.activity.time.models import TimeEntry
from apps.activity.time.summary import calculate_summary
from apps.management.pagination import CustomPaginator


def get_time_data(request):
    entries = TimeEntry.objects.all()
    number_entries = entries.count()

    default_filter = {
        "date_min": "",
        "date_max": "",
        "firm": "Campbell & Brannon",
        "matter": None,
        "keyword": "",
        "comp": None,
        "entered": 0,
        "invoice": 0,
        "order_by": "date",
    }

    filter_data = request.session.get("time_filter", {})

    if filter_data:
        filter = TimeEntryFilter(filter_data)

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

        entries = filter.qs
        user_id = filter_data.get("user")
        user_id = int(user_id) if user_id not in (None, "") else None
    else:
        filter = TimeEntryFilter(default_filter)
        entries = filter.qs
        user_id = None

    request.session["time_filter"] = filter.data
    request.session.modified = True

    summary = calculate_summary(entries)
    users = CustomUser.objects.filter(is_active=True)

    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key="time_pagination"
    )

    selected_user = None
    if user_id:
        selected_user = (
            CustomUser.objects.filter(id=user_id).first().username.capitalize()
        )

    context = {
        "edit": False,
        "objects": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "time_pagination",
        "trigger_key": "timeChanged",
        "number_entries": number_entries,
        "summary": summary,
        "users": users,
        "selected_user": selected_user,
        "user_id": user_id,
        "filter_label": filter_data.get("filter_label", None) if filter_data else None,
    }

    return context
