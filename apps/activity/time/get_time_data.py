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
from apps.tasks.tasks import adjacent_user_ids


def get_time_data(request):
    entries = TimeEntry.objects.select_related("matter").all()

    # Filter time entries for users without perm_all_matters
    if not request.user.is_admin and not request.user.perm_all_matters:
        entries = entries.filter(matter__in=request.user.assigned_matters.all())

    number_entries = entries.count()

    today_str = datetime.now().date().strftime("%Y-%m-%d")
    default_filter = {
        "filter_label": "today",
        "date_min": today_str,
        "date_max": today_str,
        "matter": None,
        "keyword": "",
        "comp": None,
        "order_by": "-date",
        "user": request.user.id,
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
        elif filter_label == "last_week":
            monday = current_date - timedelta(days=current_date.weekday())
            last_monday = monday - timedelta(days=7)
            last_sunday = monday - timedelta(days=1)
            filter.data["date_min"] = str(last_monday)
            filter.data["date_max"] = str(last_sunday)
        elif filter_label == "this_month":
            filter.data["date_min"] = str(current_date.replace(day=1))
            filter.data["date_max"] = str(current_date)
        elif filter_label == "last_month":
            month_start = current_date.replace(day=1)
            last_month_end = month_start - timedelta(days=1)
            last_month_start = last_month_end.replace(day=1)
            filter.data["date_min"] = str(last_month_start)
            filter.data["date_max"] = str(last_month_end)

        entries = filter.qs
        user_id = filter_data.get("user")
        user_id = int(user_id) if user_id not in (None, "") else None
    else:
        filter = TimeEntryFilter(default_filter, queryset=entries)
        entries = filter.qs
        user_id = request.user.id
        filter_data = default_filter
        request.session["time_filter"] = default_filter
        request.session.modified = True

    # Admin (non-billable matter) entries are never invoiced, so they would
    # otherwise inflate the unbilled view. Exclude them from both the table
    # and the summary when the unbilled quick filter is active.
    if filter.data.get("filter_label") == "unbilled":
        entries = entries.exclude(matter__billable=False)

    request.session["time_filter"] = filter.data
    request.session.modified = True

    summary = calculate_summary(entries)
    users = CustomUser.objects.filter(is_active=True).order_by("username")
    user_prev_id, user_next_id = adjacent_user_ids(users, user_id)

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

    # Filter button is the superset signal for the modal-only dimensions.
    # Date and user have dedicated dropdowns that show their own active state,
    # so they're intentionally excluded here. entered/invoice get folded in
    # only when they're NOT already conveyed by the "Unbilled" date preset.
    custom_filter_active = bool(filter_data) and any(
        [
            filter_data.get("matter") not in (None, ""),
            filter_data.get("actions", "") != "",
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
        "session_key": "time_pagination",
        "trigger_key": "timeChanged",
        "number_entries": number_entries,
        "summary": summary,
        "users": users,
        "user_prev_id": user_prev_id,
        "user_next_id": user_next_id,
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
