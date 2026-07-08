from datetime import date

from django.db.models import F

from apps.accounts.models import CustomUser
from apps.checklists.models import Checklist, UserChecklistView
from apps.management.pagination import CustomPaginator
from apps.management.selection import (
    all_visible_selected,
    get_selected_ids,
    get_session_key,
)
from apps.matters.models import Matter
from apps.tasks.constants import (
    ACTIVE_STATUSES,
    BOARD_PAGE_SIZE,
    BOARD_STATUS_ORDER,
    STATUS_BY_SLUG,
    STATUS_CHOICES,
    coerce_status,
    status_is_custom,
)
from apps.tasks.filter import TasksFilter
from apps.tasks.models import (
    Task,
    TaskNote,
    UserTaskNoteView,
)


def resolve_task_filter(request):
    """Resolve the session task filter into a queryset and selected dimensions.

    Shared by the list view and the board view so both honour the same active
    filters. Seeds a default "today" filter in the session on first visit.
    Returns (tasks, filter_data, user_id, matter_id, importance_value).
    """
    today = date.today()

    filter_data = request.session.get("tasks_filter", {})

    # Drop the legacy "All Users" sentinel (0) before binding. The user
    # filter is a ModelChoiceFilter and would otherwise fail validation.
    if filter_data.get("user") in (0, "0"):
        filter_data = dict(filter_data)
        filter_data.pop("user", None)
        request.session["tasks_filter"] = filter_data

    if filter_data:
        filter_data = {
            **filter_data,
            "status": coerce_status(filter_data.get("status")) or ACTIVE_STATUSES,
            "order_by": filter_data.get("order_by", "date_due"),
        }

        filter = TasksFilter(filter_data)
        tasks = filter.qs.select_related("matter", "user")

        user_id = filter_data.get("user")
        user_id = int(user_id) if user_id not in (None, "") else None

        matter_id = filter_data.get("matter")
        matter_id = int(matter_id) if matter_id not in (None, "") else None

        importance_value = filter_data.get("importance")
        importance_value = (
            int(importance_value) if importance_value not in (None, "", 0) else None
        )

    else:
        default_filter = {
            "filter_label": "today",
            "status": ACTIVE_STATUSES,
            "date_due_max": today.strftime("%Y-%m-%d"),
            "date_due_min": "",
            "has_due_date": "",
            "matter": None,
            "order_by": "date_due",
            "user": request.user.id,
        }
        request.session["tasks_filter"] = default_filter
        request.session.modified = True

        filter = TasksFilter(default_filter)
        tasks = filter.qs.select_related("matter", "user")

        user_id = request.user.id
        matter_id = None
        importance_value = None
        filter_data = default_filter

    return tasks, filter_data, user_id, matter_id, importance_value


def enrich_tasks(request, task_list):
    """Attach note + checklist badge state to each task in place.

    Shared by the list and board views. Sets, per task: has_notes,
    has_new_notes, has_checklist, checklist_total, checklist_done,
    checklist_complete, and has_unviewed_checklist.
    """
    task_ids = [t.id for t in task_list]

    # Get user's note view history for badge notification system
    user_note_views = UserTaskNoteView.objects.filter(
        user=request.user, task_id__in=task_ids
    ).values("task_id", "last_viewed_at")
    view_times = {v["task_id"]: v["last_viewed_at"] for v in user_note_views}

    # Notes: which tasks have any note, and which have an "unread" one — created
    # by another user after this user last viewed (or ever, if never viewed).
    # Two set-based queries instead of two .exists() per task (was N+1).
    tasks_with_notes = set(
        TaskNote.objects.filter(task_id__in=task_ids).values_list("task_id", flat=True)
    )
    tasks_with_new_notes = set()
    for tid, created_at in (
        TaskNote.objects.filter(task_id__in=task_ids)
        .exclude(user=request.user)
        .values_list("task_id", "created_at")
    ):
        last_viewed = view_times.get(tid)
        if last_viewed is None or created_at > last_viewed:
            tasks_with_new_notes.add(tid)

    # Bulk-prefetch checklists to avoid N+1
    checklists = Checklist.objects.filter(task_id__in=task_ids).prefetch_related(
        "items"
    )
    checklists_by_task = {cl.task_id: cl for cl in checklists}

    # Checklist view tracking
    checklist_views = UserChecklistView.objects.filter(
        user=request.user, task_id__in=task_ids
    ).values_list("task_id", flat=True)
    viewed_checklist_task_ids = set(checklist_views)

    for task in task_list:
        task.has_notes = task.id in tasks_with_notes
        task.has_new_notes = task.id in tasks_with_new_notes

        cl = checklists_by_task.get(task.id)
        if cl:
            task.has_checklist = True
            items = [i for i in cl.items.all() if i.item_type == "item"]
            task.checklist_total = len(items)
            task.checklist_done = sum(1 for i in items if i.is_complete)
            task.checklist_complete = task.checklist_done == task.checklist_total
            task.has_unviewed_checklist = task.id not in viewed_checklist_task_ids
        else:
            task.has_checklist = False
            task.has_unviewed_checklist = False

    return task_list


def adjacent_user_ids(users, user_id):
    """Prev/next ids on a toolbar user-stepper cycle: the active users in
    list order, wrapping at the ends. The All Users state is skipped (it stays
    reachable from the dropdown); from All Users the steppers enter the cycle
    at the last/first user. The chevrons post these to the toolbar's
    filter-user endpoint (tasks and activity/time share this)."""
    ids = [u.id for u in users]
    if not ids:
        return 0, 0
    try:
        i = ids.index(int(user_id)) if user_id else None
    except (TypeError, ValueError):
        i = None
    if i is None:
        return ids[-1], ids[0]
    return ids[i - 1], ids[(i + 1) % len(ids)]


def get_list_data(request):
    list_data = {}

    today = date.today()

    tasks, filter_data, user_id, matter_id, importance_value = resolve_task_filter(
        request
    )

    # Force-show newly created tasks at the top regardless of filters
    new_task_ids = request.session.pop("new_task_ids", [])
    edited_task_ids = request.session.pop("edited_task_ids", [])

    # Exclude new tasks from main queryset to avoid duplicates
    if new_task_ids:
        tasks = tasks.exclude(id__in=new_task_ids)

    pagination = CustomPaginator(
        tasks, per_page=20, request=request, session_key="tasks_pagination"
    )

    # Prepend new tasks to the top of the page
    if new_task_ids:
        new_tasks = list(Task.objects.filter(id__in=new_task_ids))
        task_list = new_tasks + list(pagination.get_object_list())
    else:
        task_list = pagination.get_object_list()

    enrich_tasks(request, task_list)

    selected_matter = None
    if matter_id:
        selected_matter = Matter.objects.filter(id=matter_id).first()

    selected_user = None
    if user_id:
        selected_user = CustomUser.objects.filter(id=user_id).first()

    users = CustomUser.objects.filter(is_active=True).order_by("username")
    user_prev_id, user_next_id = adjacent_user_ids(users, user_id)

    # Get current order (remove - prefix if exists)
    current_order = (
        (filter_data.get("order_by") or "date_due") if filter_data else "date_due"
    )
    current_order = current_order.lstrip("-")

    # Selection state
    selected_session_key = get_session_key("selected_tasks")
    selected_tasks = get_selected_ids(request, selected_session_key)
    visible_ids = [task.id for task in task_list]
    all_selected = all_visible_selected(selected_tasks, visible_ids)

    list_data = {
        "pagination": pagination,
        "session_key": "tasks_pagination",
        "trigger_key": "tasksListChanged",
        "objects": task_list,
        "matters": Matter.objects.filter(status__in=["Pending", "Open"]).order_by(
            "name"
        ),
        "today": today,
        "users": users,
        "user_prev_id": user_prev_id,
        "user_next_id": user_next_id,
        "importances": list(range(7, 0, -1)),
        "user_id": user_id,
        "matter_id": matter_id,
        "importance_value": importance_value,
        "selected_matter": selected_matter.name if selected_matter else "",
        "selected_user": selected_user.username.capitalize() if selected_user else "",
        "selected_importance": f"Priority {importance_value}"
        if importance_value
        else "",
        "filter_label": filter_data.get("filter_label", None) if filter_data else None,
        # Filter button is the superset signal for the modal-only dimensions.
        # Date, user, and importance have their own toolbar dropdowns (date
        # covers date_due via "Custom range" too) so they're excluded here.
        "custom_filter_active": bool(filter_data)
        and any(
            [
                status_is_custom(filter_data.get("status")),
                filter_data.get("matter") not in (None, ""),
                filter_data.get("date_completed_min") not in (None, ""),
                filter_data.get("date_completed_max") not in (None, ""),
            ]
        ),
        "current_order": current_order,
        "selected_tasks": selected_tasks,
        "all_selected": all_selected,
        "new_task_ids": new_task_ids,
        "edited_task_ids": edited_task_ids,
    }

    return list_data


def get_board_data(request):
    """Context for the Kanban board view.

    Honours the same session filters as the list view (user, matter,
    importance, date) but ignores the saved *status* filter — the board's
    columns are the status dimension, so every status is always shown. Columns
    are laid out in BOARD_STATUS_ORDER and tasks within a column are ordered by
    custom_order (manual drag order) then due date.
    """
    today = date.today()

    _, filter_data, user_id, matter_id, importance_value = resolve_task_filter(request)

    # Replace the status filter with the full set so all four columns render;
    # keep every other active filter intact.
    board_filter = {k: v for k, v in filter_data.items() if k != "order_by"}
    board_filter["status"] = [value for value, _ in STATUS_CHOICES]

    tasks = (
        TasksFilter(board_filter)
        .qs.select_related("matter", "user")
        .order_by(F("custom_order").asc(nulls_last=True), "date_due", "id")
    )

    task_list = list(tasks)
    enrich_tasks(request, task_list)

    grouped = {value: [] for value, _ in STATUS_CHOICES}
    for task in task_list:
        if task.status in grouped:
            grouped[task.status].append(task)

    slug_by_status = {value: slug for slug, value in STATUS_BY_SLUG.items()}
    status_labels = dict(STATUS_CHOICES)
    # Cap each column at its session limit (default BOARD_PAGE_SIZE) so a column
    # with hundreds of cards — typically Completed — doesn't bloat the board.
    # "Show more" bumps the limit (see tasks_board_show_more). count stays the
    # true total; tasks is the visible slice. Just-created tasks (custom_order is
    # null, so they'd sort to the bottom) are pulled to the front so a card added
    # via the column quick-add is always visible, even past the cap.
    limits = request.session.get("tasks_board_limits", {})
    new_ids = set(request.session.pop("new_task_ids", []))
    columns = []
    for value in BOARD_STATUS_ORDER:
        slug = slug_by_status[value]
        col_tasks = grouped[value]
        if new_ids and any(t.id in new_ids for t in col_tasks):
            fresh = [t for t in col_tasks if t.id in new_ids]
            col_tasks = fresh + [t for t in col_tasks if t.id not in new_ids]
        total = len(col_tasks)
        limit = limits.get(slug, BOARD_PAGE_SIZE)
        visible = col_tasks[:limit]
        columns.append(
            {
                "label": status_labels[value],
                "slug": slug,
                "tasks": visible,
                "count": total,
                "has_more": total > len(visible),
                "remaining": total - len(visible),
            }
        )

    selected_matter = Matter.objects.filter(id=matter_id).first() if matter_id else None
    selected_user = CustomUser.objects.filter(id=user_id).first() if user_id else None

    users = CustomUser.objects.filter(is_active=True).order_by("username")
    user_prev_id, user_next_id = adjacent_user_ids(users, user_id)

    selected_session_key = get_session_key("selected_tasks")
    selected_tasks = get_selected_ids(request, selected_session_key)

    return {
        "columns": columns,
        "view_mode": "board",
        "trigger_key": "tasksListChanged",
        "today": today,
        "users": users,
        "user_prev_id": user_prev_id,
        "user_next_id": user_next_id,
        "importances": list(range(7, 0, -1)),
        "user_id": user_id,
        "matter_id": matter_id,
        "importance_value": importance_value,
        "selected_matter": selected_matter.name if selected_matter else "",
        "selected_user": selected_user.username.capitalize() if selected_user else "",
        "selected_importance": f"Priority {importance_value}"
        if importance_value
        else "",
        "filter_label": filter_data.get("filter_label", None) if filter_data else None,
        "custom_filter_active": bool(filter_data)
        and any(
            [
                status_is_custom(filter_data.get("status")),
                filter_data.get("matter") not in (None, ""),
                filter_data.get("date_completed_min") not in (None, ""),
                filter_data.get("date_completed_max") not in (None, ""),
            ]
        ),
        "selected_tasks": selected_tasks,
    }
