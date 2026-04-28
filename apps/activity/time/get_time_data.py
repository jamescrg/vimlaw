from datetime import datetime, timedelta

from apps.accounts.models import CustomUser
from apps.activity.time.filter import TimeEntryFilter
from apps.activity.time.models import TimeEntry
from apps.activity.time.summary import calculate_summary
from apps.management.pagination import CustomPaginator
from apps.management.selection import (
    all_visible_selected,
    get_selected_ids,
    get_session_key,
)
from apps.matters.models import Matter


def get_time_data(request):
    entries = TimeEntry.objects.select_related("matter").all()

    # Filter time entries for users without perm_all_matters
    if not request.user.is_admin and not request.user.perm_all_matters:
        entries = entries.filter(matter__in=request.user.assigned_matters.all())

    number_entries = entries.count()

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

    filter_data = request.session.get("time_filter", {})

    # Clean up legacy sessions that stored the "All Users" sentinel (0) — it
    # isn't a valid pk for the ModelChoiceFilter and trips form validation.
    if filter_data.get("user") in (0, "0"):
        filter_data.pop("user", None)

    if filter_data:
        filter = TimeEntryFilter(filter_data, queryset=entries)

        current_date = datetime.now().date()
        filter_label = filter.data.get("filter_label", None)

        # Recalculate dates for relative quick filters
        if filter_label == "today":
            filter.data["date_min"] = str(current_date)
            filter.data["date_max"] = str(current_date)
        elif filter_label == "yesterday":
            yesterday = current_date - timedelta(days=1)
            filter.data["date_min"] = str(yesterday)
            filter.data["date_max"] = str(yesterday)
        elif filter_label == "this_week":
            monday = current_date - timedelta(days=current_date.weekday())
            filter.data["date_min"] = str(monday)
            filter.data["date_max"] = str(current_date)
        elif filter_label == "this_month":
            filter.data["date_min"] = str(current_date.replace(day=1))
            filter.data["date_max"] = str(current_date)

        entries = filter.qs
        user_id = filter_data.get("user")
        user_id = int(user_id) if user_id not in (None, "") else None
    else:
        filter = TimeEntryFilter(default_filter, queryset=entries)
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
        user = CustomUser.objects.filter(id=user_id).first()
        if user:
            selected_user = user.username.capitalize()

    # Get current order and strip leading '-' for comparison
    current_order = filter_data.get("order_by", "-date") if filter_data else "-date"
    current_order = current_order.lstrip("-")

    # Get selection data
    session_key = get_session_key("selected_time")
    selected_time = get_selected_ids(request, session_key)

    visible_ids = [entry.id for entry in pagination.get_object_list()]
    all_selected = all_visible_selected(selected_time, visible_ids)

    # Filter button highlights when modal-specific fields have non-default values
    custom_filter_active = filter_data and any(
        [
            filter_data.get("comp") not in (None, ""),
            filter_data.get("matter") not in (None, ""),
            filter_data.get("keyword", "") != "",
        ]
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
        "custom_filter_active": custom_filter_active,
        "current_order": current_order,
        "selected_time": selected_time,
        "all_selected": all_selected,
        "matters": Matter.objects.filter(
            status__in=["Pending", "Open", "Complete"]
        ).order_by("name"),
    }

    return context
