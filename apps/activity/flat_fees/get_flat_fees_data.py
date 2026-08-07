from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.activity.flat_fees.filter import FlatFeeEntryFilter
from apps.activity.flat_fees.models import FlatFeeEntry
from apps.activity.flat_fees.summary import calculate_summary
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


def get_flat_fees_data(request):
    entries = FlatFeeEntry.objects.select_related("matter").all()

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

    filter_data = request.session.get("flat_fees_filter", {})

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
        filter = FlatFeeEntryFilter(filter_data, queryset=entries)

        entries = filter.qs
        user_id = filter_data.get("user")
        user_id = int(user_id) if user_id not in (None, "") else None
    else:
        filter = FlatFeeEntryFilter(default_filter, queryset=entries)
        entries = filter.qs
        user_id = None

    request.session["flat_fees_filter"] = filter.data
    request.session.modified = True

    summary = calculate_summary(entries)
    users = CustomUser.objects.filter(is_active=True).order_by("username")

    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key="flat_fees_pagination"
    )

    selected_user = None
    if user_id:
        user = CustomUser.objects.filter(id=user_id).first()
        if user:
            selected_user = user.username.capitalize()

    current_order = filter_data.get("order_by", "-date") if filter_data else "-date"
    current_order = current_order.lstrip("-")

    session_key = get_session_key("selected_flat_fees")
    selected_flat_fees = get_selected_ids(request, session_key)

    visible_ids = [entry.id for entry in pagination.get_object_list()]
    all_selected = all_visible_selected(selected_flat_fees, visible_ids)

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
        "session_key": "flat_fees_pagination",
        "trigger_key": "flatFeesChanged",
        "number_entries": number_entries,
        "summary": summary,
        "users": users,
        "user_chips": get_user_chips(request, users, user_id),
        "chip_pinned_ids": request.user.task_user_chips or [],
        "selected_user": selected_user,
        "user_id": user_id,
        "filter_label": filter_data.get("filter_label", None) if filter_data else None,
        "custom_filter_active": custom_filter_active,
        "current_order": current_order,
        "selected_flat_fees": selected_flat_fees,
        "all_selected": all_selected,
        "matters": Matter.objects.filter(
            billing_type="FLAT_FEE",
            status__in=["Pending", "Open", "Complete"],
        ).order_by("name"),
    }

    return context
