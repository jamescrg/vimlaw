import json
import logging
from datetime import datetime

import markdown
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import CustomUser
from apps.checklists.models import can_complete_task
from apps.management.pagination import CustomPaginator
from apps.management.selection import (
    clear_selected_ids,
    get_selected_ids,
    get_session_key,
    select_all_ids,
    selection_response,
    toggle_id,
)
from apps.management.user_filter import cycle_user_filter
from apps.matters.models import Matter
from apps.tasks.constants import (
    ACTIVE_STATUSES,
    BOARD_PAGE_SIZE,
    STATUS_BY_SLUG,
    STATUS_COMPLETE,
    STATUS_PENDING,
    coerce_status,
)
from apps.tasks.filter import TasksFilter
from apps.tasks.forms import BulkTasksForm, TaskForm, TaskNoteForm
from apps.tasks.models import (
    Task,
    TaskNote,
    UserTaskNoteView,
)
from apps.tasks.services import (
    clamp_importance,
    detect_filter_label as _detect_filter_label,
    parse_due_date,
    process_quick_task_description,
    quick_date_filters,
    refresh_date_preset,
    resolve_assignee_name,
    resolve_matter_name,
)
from apps.tasks.tasks import get_board_data, get_list_data
from utils.toasts import toast_success, toast_warning

logger = logging.getLogger(__name__)

TASKS_TRIGGER = "tasksListChanged"


def _tasks_view_context(request):
    """Pick the list or board view based on the session view mode.

    Returns (inner_template, context). Both views share the #tasks container
    and the tasksListChanged refresh loop, so the toggle just flips which
    template this resolves to.
    """
    view_mode = request.session.get("tasks_view_mode", "list")
    if view_mode == "board":
        return "tasks/board.html", get_board_data(request)
    context = get_list_data(request)
    context["view_mode"] = "list"
    return "tasks/list.html", context


def _render_tasks(request):
    """Render the current tasks fragment (list or board) for the #tasks target.

    Shared by tasks_list and by every mutation endpoint that used to
    redirect("tasks:list"); returning the fragment directly drops the extra
    POST -> 302 -> GET round-trip.
    """
    inner_template, context = _tasks_view_context(request)
    return render(request, inner_template, context)


@login_required
def tasks_index(request):
    # Start each full board load with every column collapsed to one page; the
    # per-column "Show more" expansions are only meant to last within a session
    # of working on the board, not to persist a 350-card Completed column.
    request.session.pop("tasks_board_limits", None)
    inner_template, context = _tasks_view_context(request)
    context = context | {
        "app": "tasks",
        "inner_template": inner_template,
    }
    return render(request, "tasks/tasks.html", context)


@login_required
@require_POST
def tasks_board_show_more(request, slug):
    """Reveal another page of cards in a board column (raise its render limit)."""
    if slug in STATUS_BY_SLUG:
        limits = request.session.get("tasks_board_limits", {})
        limits[slug] = limits.get(slug, BOARD_PAGE_SIZE) + BOARD_PAGE_SIZE
        request.session["tasks_board_limits"] = limits
        request.session.modified = True
    return HttpResponse(status=204, headers={"HX-Trigger": TASKS_TRIGGER})


@login_required
def tasks_list(request):
    return _render_tasks(request)


@login_required
def tasks_toolbar(request):
    """Render just the tasks toolbar (bulk actions + selection count).

    Used after a shift-click selection change so the board doesn't have to be
    re-rendered and its Sortables re-initialised on every click.
    """
    _, context = _tasks_view_context(request)
    return render(request, "tasks/toolbar.html", context)


@login_required
@require_POST
def tasks_set_view_mode(request, mode):
    """Toggle between the list and board (Kanban) views; persist in session."""
    if mode not in ("list", "board"):
        raise Http404("Unknown view mode")
    request.session["tasks_view_mode"] = mode
    request.session.modified = True
    return HttpResponse(status=204, headers={"HX-Trigger": TASKS_TRIGGER})


@login_required
@require_POST
def tasks_board_move(request):
    """Persist a Kanban drag: set the card's status and the column's order.

    Body JSON: {task_id, status_slug, ordered_ids}. ordered_ids is the full
    top-to-bottom list of task ids in the destination column after the drop.
    Returns {ok: bool, message?}; the client reverts the board (re-render) on
    a falsy ok, e.g. when an incomplete checklist blocks Completion.
    """
    try:
        payload = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "message": "Invalid request."}, status=400)

    task = get_object_or_404(Task, pk=payload.get("task_id"))
    status = STATUS_BY_SLUG.get(payload.get("status_slug"))
    if status is None:
        return JsonResponse({"ok": False, "message": "Unknown status."}, status=400)

    if status == STATUS_COMPLETE and not can_complete_task(task):
        return JsonResponse(
            {
                "ok": False,
                "message": "Please complete all checklist items before "
                "marking this task as done.",
            }
        )

    if task.status != status:
        task.status = status
        task.save()

    # Persist the destination column's order as sequential custom_order values.
    id_to_order = {
        int(tid): index for index, tid in enumerate(payload.get("ordered_ids", []))
    }
    for t in Task.objects.filter(id__in=id_to_order.keys()):
        new_order = id_to_order[t.id]
        if t.custom_order != new_order:
            t.custom_order = new_order
            t.save(update_fields=["custom_order"])

    return JsonResponse({"ok": True})


@login_required
@require_POST
def tasks_board_bulk_move(request):
    """Move every selected task to a status (Kanban stacked bulk drag).

    Body JSON: {status_slug}. Reads the selection from the session, mirrors the
    single-card move's completion guard per task, and skips any that can't be
    completed. Returns {ok, skipped, message}; the client refreshes the board and
    shows a warning toast when tasks were skipped (a fetch can't read HX-Toast).
    """
    try:
        payload = json.loads(request.body)
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "message": "Invalid request."}, status=400)

    status = STATUS_BY_SLUG.get(payload.get("status_slug"))
    if status is None:
        return JsonResponse({"ok": False, "message": "Unknown status."}, status=400)

    key = get_session_key("selected_tasks")
    selected = get_selected_ids(request, key)
    if not selected:
        return JsonResponse({"ok": False, "message": "No tasks selected."}, status=400)

    skipped = 0
    for task in Task.objects.filter(id__in=selected):
        if status == STATUS_COMPLETE and not can_complete_task(task):
            skipped += 1
            continue
        if task.status != status:
            task.status = status
            task.save()

    clear_selected_ids(request, key)

    message = ""
    if skipped:
        message = f"{skipped} task(s) skipped — complete their checklists first."
    return JsonResponse({"ok": True, "skipped": skipped, "message": message})


@login_required
def tasks_select(request):
    return redirect("tasks:index")


@login_required
def tasks_add(request):
    if request.method == "POST":
        form = TaskForm(request.POST, user=request.user, use_required_attribute=False)
        if form.is_valid():
            task = form.save(commit=False)
            # The board's per-column "+" opens this modal with ?status=<slug> so
            # the card lands in that column; elsewhere it defaults to Pending.
            task.status = STATUS_BY_SLUG.get(request.GET.get("status"), STATUS_PENDING)
            task.save()

            # Store new task ID for force-show in filtered lists
            new_task_ids = request.session.get("new_task_ids", [])
            new_task_ids.append(task.id)
            request.session["new_task_ids"] = new_task_ids

            if task.matter:
                request.session["tasks_matter"] = task.matter.id
            response = HttpResponse(
                status=204, headers={"HX-Trigger": "tasksListChanged"}
            )
            if request.GET.get("from") == "palette":
                toast_success(response, f"Task created for {task.user.full_name}.")
            return response

    else:
        # get the currently filtered user if available
        filter_data = request.session.get("tasks_filter", {})
        user_id = filter_data.get("user")

        # automatically populate to the current matter
        tasks_matter = filter_data.get("matter")

        # if no current matter is set, use the matter to which
        # the most recently saved task was assigned
        if not tasks_matter:
            tasks_matter = request.session.get("tasks_matter")

        if user_id and user_id != "":
            try:
                initial_user = CustomUser.objects.get(pk=int(user_id))
            except (ValueError, CustomUser.DoesNotExist):
                initial_user = request.user
        else:
            initial_user = request.user

        form = TaskForm(
            initial={
                "user": initial_user,
                "matter": tasks_matter,
                "date_due": timezone.localdate(),
            },
            user=request.user,
            use_required_attribute=False,
        )

    matters = Matter.objects.filter(status__in=["Pending", "Open"]).order_by("name")
    form.fields["matter"].queryset = matters
    form.fields["matter"].empty_label = "Admin"
    users = CustomUser.objects.filter(is_active=True).order_by("username")
    form.fields["user"].queryset = users

    # When no matter is pre-selected, autofocus the matter select instead of description
    if not tasks_matter:
        form.fields["description"].widget.attrs.pop("autofocus", None)
        form.fields["matter"].widget.attrs["autofocus"] = "autofocus"

    context = {
        "app": "tasks",
        "edit": False,
        "add": True,
        "form": form,
    }

    return render(request, "tasks/form.html", context)


@login_required
def tasks_add_quick(request):
    # prevent creation of tasks without a description
    if not request.POST["description"]:
        return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})

    filter_data = request.session.get("tasks_filter", {})

    # AI path first: Gemini Flash interprets the whole line. Nulls mean
    # "not stated", filled with the same defaults the legacy path uses.
    entry = _quick_add_ai_entry(request)
    if entry is not None:
        task = Task(status=STATUS_PENDING)
        task.description = str(entry.get("description"))[:200]

        task.date_due = parse_due_date(entry.get("due")) or timezone.localdate()

        if entry.get("importance") is not None:
            task.importance = clamp_importance(entry.get("importance"))
        else:
            filter_importance = filter_data.get("importance")
            task.importance = (
                int(filter_importance)
                if filter_importance and int(filter_importance) != 0
                else 4
            )

        assignee = None
        if entry.get("user"):
            assignee = resolve_assignee_name(entry.get("user"), None)
        if assignee is None:
            user_id = filter_data.get("user") or request.user.id
            assignee = CustomUser.objects.filter(pk=int(user_id)).get()
        task.user = assignee

        matter = resolve_matter_name(entry.get("matter"))
        if matter is None and not entry.get("matter"):
            matter_id = filter_data.get("matter", None)
            if matter_id:
                matter = Matter.objects.filter(pk=int(matter_id)).first()
        task.matter = matter

        task.save()
        response = HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})
        matter_name = task.matter.name if task.matter else "Admin"
        details = [matter_name, f"due {task.date_due}"]
        if task.user_id != request.user.id:
            details.append(f"for {task.user.full_name}")
        toast_success(response, f"Added to {', '.join(details)}.")
        if entry.get("matter") and task.matter is None:
            toast_warning(
                response,
                f'No open matter matches "{entry["matter"]}". '
                f"The task was filed under Admin.",
            )
        return _finish_quick_add(request, task, response)

    # Legacy path: prefix matcher (also the fallback when the AI is down)
    last_matter_id = request.session.get("last_quick_task_matter")
    match = process_quick_task_description(request.POST["description"], last_matter_id)
    description = match.description

    # Prevent creation of tasks with empty description after processing
    if not description.strip():
        return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})

    # set task description and some property values
    task = Task()
    task.description = description
    task.status = STATUS_PENDING
    task.date_due = timezone.localdate()

    # auto populate importance from filter
    filter_importance = filter_data.get("importance")
    if filter_importance and int(filter_importance) != 0:
        task.importance = int(filter_importance)
    else:
        task.importance = 4

    # auto populate the user
    user_id = filter_data.get("user", None)
    if not user_id:
        user_id = request.user.id
    task.user = CustomUser.objects.filter(pk=int(user_id)).get()

    # Set matter: use smart matching if applicable, otherwise use filter matter
    if match.use_smart_matching:
        task.matter = match.matter
    else:
        matter_id = filter_data.get("matter", None)
        if matter_id:
            task.matter = Matter.objects.filter(pk=int(matter_id)).get()

    task.save()

    # Flag when the typed prefix could not be resolved instead of silently
    # misfiling the task. A clean match stays quiet to keep rapid entry fast.
    response = HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})
    matter_name = task.matter.name if task.matter else "Admin"
    if match.status == "ambiguous":
        toast_warning(
            response,
            f'"{match.prefix}" matches more than one matter. It was added to '
            f"{matter_name}; type more of the name next time.",
        )
    elif match.status == "unmatched":
        toast_warning(
            response,
            f'No open matter matches "{match.prefix}". It was added to {matter_name}.',
        )
    return _finish_quick_add(request, task, response)


def _quick_add_ai_entry(request):
    """Interpret the quick-add line with AI; None whenever the firm hasn't
    opted in or the call fails, so the caller falls back to the fuzzy
    prefix matcher (the default)."""
    from apps.settings.models import Firm
    from apps.tasks.ai import interpret_quick_add

    firm = Firm.objects.first()
    if not (firm and firm.quick_task_ai):
        return None

    recent_matter = None
    last_matter_id = request.session.get("last_quick_task_matter")
    if last_matter_id:
        recent_matter = (
            Matter.objects.filter(pk=last_matter_id)
            .values_list("name", flat=True)
            .first()
        )
    try:
        entry = interpret_quick_add(
            request.POST["description"],
            request.user,
            recent_matter=recent_matter,
            model=firm.quick_task_ai_model,
        )
    except Exception:
        logger.exception("Quick-add AI interpretation failed; using legacy parser")
        return None
    if entry and len(str(entry.get("description", "")).strip()) >= 4:
        return entry
    return None


def _finish_quick_add(request, task, response):
    """Shared tail: highlight the new row and remember the matter."""
    new_task_ids = request.session.get("new_task_ids", [])
    new_task_ids.append(task.id)
    request.session["new_task_ids"] = new_task_ids
    request.session["last_quick_task_matter"] = task.matter.id if task.matter else None
    return response


@login_required
def tasks_edit(request, id):
    task = get_object_or_404(Task, pk=id)

    if request.method == "POST":
        form = TaskForm(request.POST, instance=task, user=request.user)
        if form.is_valid():
            task = form.save(commit=False)
            if task.status == STATUS_COMPLETE and not can_complete_task(task):
                form.add_error(
                    "status",
                    "Please complete all checklist items before marking this task as done.",
                )
            else:
                task.save()
                request.session["edited_task_ids"] = [task.id]
                return HttpResponse(
                    status=204, headers={"HX-Trigger": "tasksListChanged"}
                )

    else:
        form = TaskForm(instance=task, user=request.user)

    # pull the list of matters
    matter_list = Matter.objects.filter(status__in=["Pending", "Open"]).order_by("name")

    # make sure the matter associated with the event is in the list
    # if not, add it
    # this ensures the matter is available in the form select element
    # even when the matter is closed
    if task.matter and task.matter not in matter_list:
        matter_list |= Matter.objects.filter(pk=task.matter.id)
    form.fields["matter"].queryset = matter_list
    form.fields["matter"].empty_label = "Admin"
    users = CustomUser.objects.filter(is_active=True).order_by("username")
    form.fields["user"].queryset = users

    context = {
        "app": "tasks",
        "edit": True,
        "task": task,
        "form": form,
    }

    return render(request, "tasks/form.html", context)


@login_required
def tasks_delete(request, id):
    entry = get_object_or_404(Task, pk=id)
    entry.delete()
    return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})


@login_required
def tasks_filter(request, user=None):
    if request.method == "POST":
        # Merge into existing session so unmodified quick-filter state is
        # preserved; skip the CSRF token explicitly. status is multi-valued, so
        # read it via getlist (the items() loop would keep only the last box).
        filter_data = dict(request.session.get("tasks_filter", {}))
        for key, val in request.POST.items():
            if key in ("csrfmiddlewaretoken", "status"):
                continue
            filter_data[key] = val
        filter_data["status"] = request.POST.getlist("status")
        # The has_due_date NullBooleanSelect posts "unknown" for its empty
        # state; normalize it to "" so it reads as "no preference" rather than
        # a real value (which would flip the date dropdown to Custom range and
        # light the Filter button).
        if filter_data.get("has_due_date") == "unknown":
            filter_data["has_due_date"] = ""
        filter_data["filter_label"] = _detect_filter_label(
            filter_data, timezone.localdate()
        )
        request.session["tasks_filter"] = filter_data
        return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})

    else:
        filter_data = request.session.get("tasks_filter", {})

        if filter_data:
            # Sanitize filter data to remove invalid values
            sanitized_data = filter_data.copy()

            # Drop the legacy "All Users" sentinel (0). Note: the truthiness
            # check below would skip 0, leaving it to fail validation later.
            if sanitized_data.get("user") in (0, "0"):
                sanitized_data["user"] = ""

            # Validate user field - remove if invalid or inactive
            if "user" in sanitized_data and sanitized_data["user"]:
                try:
                    user_id = int(sanitized_data["user"])
                    if not CustomUser.objects.filter(
                        id=user_id, is_active=True
                    ).exists():
                        sanitized_data["user"] = ""
                except (ValueError, TypeError):
                    sanitized_data["user"] = ""

            # Validate matter field - remove if invalid
            if "matter" in sanitized_data and sanitized_data["matter"]:
                try:
                    matter_id = int(sanitized_data["matter"])
                    if not Matter.objects.filter(
                        id=matter_id, status__in=["Pending", "Open"]
                    ).exists():
                        sanitized_data["matter"] = ""
                except (ValueError, TypeError):
                    sanitized_data["matter"] = ""

            # Coerce status to a list so the multi-select binds and pre-checks
            # the right boxes; legacy single-string sessions self-heal here.
            sanitized_data["status"] = (
                coerce_status(sanitized_data.get("status")) or ACTIVE_STATUSES
            )

            # Re-derive semantic date presets so the modal's date inputs show
            # the current window (a stored "Today" always means today).
            sanitized_data = refresh_date_preset(sanitized_data, timezone.localdate())

            # Persist the cleanup so legacy poisoned sessions self-heal.
            if sanitized_data != filter_data:
                request.session["tasks_filter"] = sanitized_data

            filter = TasksFilter(sanitized_data, queryset=Task.objects.all())

            # If the filter is invalid, reset to defaults
            if not filter.form.is_valid():
                default_filter = {
                    "status": ACTIVE_STATUSES,
                    "matter": None,
                    "order_by": "date_due",
                    "user": request.user.id,
                }
                filter = TasksFilter(default_filter, queryset=Task.objects.all())
        else:
            default_filter = {
                "status": ACTIVE_STATUSES,
                "matter": None,
                "order_by": "date_due",
                "user": request.user.id,
            }

            filter = TasksFilter(default_filter, queryset=Task.objects.all())

        return render(request, "tasks/filter.html", {"filter": filter})


@login_required
def tasks_filter_quick(request, quick_filter):
    quick_filters = quick_date_filters(timezone.localdate())

    filter_data = request.session.get("tasks_filter", {})
    filter_data.update(quick_filters[quick_filter])
    request.session["tasks_filter"] = filter_data
    request.session.modified = True

    # Honour the active view mode so a date filter doesn't bounce a board
    # user back to the list.
    return _render_tasks(request)


@login_required
def tasks_filter_matter(request, matter_id):
    filter_data = request.session.get("tasks_filter", {})
    # matter_id=0 clears the matter dimension.
    filter_data["matter"] = "" if matter_id == 0 else matter_id

    request.session["tasks_filter"] = filter_data

    return _render_tasks(request)


@login_required
def tasks_filter_user(request, user_id):
    filter_data = request.session.get("tasks_filter", {})
    # The "All Users" dropdown item posts user_id=0 as a sentinel. The user
    # filter is a ModelChoiceFilter over active CustomUsers, so storing 0
    # later trips form validation when the filter modal is rendered. Treat
    # 0 as "clear the filter" instead.
    if user_id == 0:
        filter_data.pop("user", None)
    else:
        filter_data["user"] = user_id

    request.session["tasks_filter"] = filter_data

    return _render_tasks(request)


@login_required
@require_POST
def tasks_toggle_chip(request, user_id):
    """Pin or unpin a user on the toolbar's chip row (per-viewer, capped)."""
    from apps.tasks.tasks import TASK_CHIPS_CAP

    get_object_or_404(CustomUser, pk=user_id, is_active=True)
    pinned = list(request.user.task_user_chips or [])
    if user_id in pinned:
        pinned.remove(user_id)
    elif len(pinned) >= TASK_CHIPS_CAP:
        response = _render_tasks(request)
        toast_warning(
            response,
            f"Chips are limited to {TASK_CHIPS_CAP}. Unpin one first.",
        )
        return response
    else:
        pinned.append(user_id)
    request.user.task_user_chips = pinned
    request.user.save(update_fields=["task_user_chips"])
    return _render_tasks(request)


@login_required
@require_POST
def tasks_cycle_user(request, direction):
    """Cycle the task user filter (u / U keyboard shortcut)."""
    cycle_user_filter(request, "tasks_filter", direction)
    return HttpResponse(status=204, headers={"HX-Trigger": TASKS_TRIGGER})


@login_required
def tasks_filter_importance(request, importance_value):
    filter_data = request.session.get("tasks_filter", {})
    # Set to empty string when 0 (All) is selected, otherwise use the value
    filter_data["importance"] = "" if importance_value == 0 else importance_value

    request.session["tasks_filter"] = filter_data

    return _render_tasks(request)


@login_required
def tasks_filter_default(request):
    filter_data = {
        "filter_label": "today",
        "status": ACTIVE_STATUSES,
        "date_due_max": timezone.localdate().strftime("%Y-%m-%d"),
        "date_due_min": "",
        "has_due_date": "",
        "matter": None,
        "user": request.user.id,
        "order_by": "date_due",
    }
    request.session["tasks_filter"] = filter_data
    request.session.modified = True
    if request.headers.get("HX-Request"):
        return _render_tasks(request)
    return redirect("tasks:index")


@login_required
def tasks_status(request, id):
    task = get_object_or_404(Task, pk=id)
    if task.status == STATUS_COMPLETE:
        task.status = STATUS_PENDING
    else:
        if not can_complete_task(task):
            response = HttpResponse(status=204)
            response["HX-Toast"] = json.dumps(
                {
                    "type": "warning",
                    "message": "Please complete all checklist items before marking this task as done.",
                }
            )
            return response
        task.status = STATUS_COMPLETE
    task.save()
    return _render_tasks(request)


@login_required
def tasks_set_status(request, task_id, status):
    task = get_object_or_404(Task, pk=task_id)
    # status arrives as a slug ("in-progress") so spaced labels never travel in
    # the URL path; map it back to the stored display value.
    status = STATUS_BY_SLUG.get(status)
    if status is None:
        raise Http404("Unknown status")
    if status == STATUS_COMPLETE and not can_complete_task(task):
        response = HttpResponse(status=204)
        response["HX-Toast"] = json.dumps(
            {
                "type": "items incomplete",
                "message": "Please complete all checklist items before marking this task as done.",
            }
        )
        return response
    task.status = status
    task.save()
    return _render_tasks(request)


@login_required
def tasks_change_user(request, task_id):
    task = get_object_or_404(Task, pk=task_id)
    user = get_object_or_404(CustomUser, pk=request.POST["user"])
    users = CustomUser.objects.filter(is_active=True)
    task.user = user
    task.save()
    context = {
        "task": task,
        "user": user,
        "users": users,
    }
    return render(request, "tasks/change-user.html", context)


@login_required
def tasks_importance(request, task_id, importance):
    task = get_object_or_404(Task, pk=task_id)
    task.importance = importance
    task.save()
    request.session["edited_task_ids"] = [task.id]
    return _render_tasks(request)


@login_required
def tasks_date(request, task_id):
    task = get_object_or_404(Task, pk=task_id)

    if request.method == "POST":
        try:
            date_due = datetime.strptime(request.POST["date_due"], "%Y-%m-%d")
        except ValueError:
            date_due = None
        task.date_due = date_due
        task.save()
        request.session["edited_task_ids"] = [task.id]
        return _render_tasks(request)

    else:
        context = {
            "task": task,
        }
        return render(request, "tasks/date-edit.html", context)


@login_required
def tasks_user(request, task_id, user):
    task = get_object_or_404(Task, pk=task_id)
    user = get_object_or_404(CustomUser, pk=user)
    task.user = user
    task.save()
    return _render_tasks(request)


@login_required
def tasks_matter(request, task_id, matter_id):
    task = get_object_or_404(Task, pk=task_id)
    if matter_id == 0:
        task.matter = None
    else:
        matter = get_object_or_404(Matter, pk=matter_id)
        task.matter = matter
    task.save()
    return _render_tasks(request)


@login_required
def tasks_filter_sort(request, order):
    filter_data = request.session.get("tasks_filter", {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["tasks_filter"] = filter_data

    return _render_tasks(request)


@login_required
def clear_tasks(request):
    # Delete all the tasks from the filter that are marked as complete
    filter_data = dict(request.session.get("tasks_filter", {}))
    # Coerce status to a list so a legacy single-string session doesn't trip the
    # MultipleChoiceFilter validation when the filter is bound here.
    filter_data["status"] = coerce_status(filter_data.get("status")) or ACTIVE_STATUSES
    filter = TasksFilter(filter_data)
    filter.qs.filter(status=STATUS_COMPLETE).delete()
    return _render_tasks(request)


@login_required
def tasks_add_note(request, id):
    task = get_object_or_404(Task, pk=id)
    matter_id = request.GET.get("matter_id") or request.POST.get("matter_id")

    if request.method == "POST":
        form = TaskNoteForm(request.POST, use_required_attribute=False)
        if form.is_valid():
            note = form.save(commit=False)
            note.task = task
            note.user = request.user
            note.save()
            redirect_url = f"/tasks/{task.id}/detail/"
            if matter_id:
                redirect_url += f"?matter_id={matter_id}"
            return redirect(redirect_url)
    else:
        form = TaskNoteForm(
            initial={
                "date": timezone.localdate(),
                "time": datetime.now().strftime("%H:%M"),
            },
            use_required_attribute=False,
        )

    action = f"/tasks/{id}/add-note/"
    if matter_id:
        action += f"?matter_id={matter_id}"

    context = {
        "task": task,
        "form": form,
        "edit": False,
        "action": action,
        "matter_id": matter_id,
    }
    return render(request, "tasks/form_note.html", context)


@login_required
def tasks_detail(request, id):
    task = get_object_or_404(Task, pk=id)
    notes = task.notes.all()
    matter_id = request.GET.get("matter_id")

    # Reset to page 1 unless this is a pagination request
    if not request.headers.get("HX-Trigger-Name") == "taskNotesChanged":
        request.session["task_notes_pagination"] = 1

    # Track view for badge notification system
    UserTaskNoteView.objects.update_or_create(
        user=request.user,
        task=task,
        # last_viewed_at auto-updates with auto_now=True
    )

    pagination = CustomPaginator(
        notes, per_page=5, request=request, session_key="task_notes_pagination"
    )
    page_notes = pagination.get_object_list()

    # Process markdown in note details
    for note in page_notes:
        if note.details:
            note.details = markdown.markdown(note.details)

    context = {
        "task": task,
        "notes": page_notes,
        "pagination": pagination,
        "session_key": "task_notes_pagination",
        "trigger_key": "taskNotesChanged",
        "matter_id": matter_id,
    }
    return render(request, "tasks/detail.html", context)


@login_required
def tasks_detail_notes(request, id):
    """Return just the notes partial for HTMX pagination."""
    task = get_object_or_404(Task, pk=id)
    notes = task.notes.all()
    matter_id = request.GET.get("matter_id")

    # Accept page param directly so pagination doesn't need a trigger round-trip
    page = request.GET.get("page")
    if page:
        request.session["task_notes_pagination"] = int(page)

    pagination = CustomPaginator(
        notes, per_page=5, request=request, session_key="task_notes_pagination"
    )
    page_notes = pagination.get_object_list()

    for note in page_notes:
        if note.details:
            note.details = markdown.markdown(note.details)

    context = {
        "task": task,
        "notes": page_notes,
        "pagination": pagination,
        "session_key": "task_notes_pagination",
        "trigger_key": "taskNotesChanged",
        "matter_id": matter_id,
    }
    return render(request, "tasks/detail-notes.html", context)


@login_required
def tasks_edit_note(request, id):
    note = get_object_or_404(TaskNote, pk=id)
    matter_id = request.GET.get("matter_id") or request.POST.get("matter_id")

    if request.method == "POST":
        form = TaskNoteForm(request.POST, instance=note, use_required_attribute=False)
        if form.is_valid():
            form.save()
            redirect_url = f"/tasks/{note.task.id}/detail/"
            if matter_id:
                redirect_url += f"?matter_id={matter_id}"
            return redirect(redirect_url)
    else:
        form = TaskNoteForm(instance=note, use_required_attribute=False)

    action = f"/tasks/note/{id}/edit/"
    if matter_id:
        action += f"?matter_id={matter_id}"

    context = {
        "task": note.task,
        "note": note,
        "form": form,
        "edit": True,
        "action": action,
        "matter_id": matter_id,
    }
    return render(request, "tasks/form_note.html", context)


@login_required
def tasks_delete_note(request, id):
    note = get_object_or_404(TaskNote, pk=id)
    task_id = note.task.id
    matter_id = request.GET.get("matter_id") or request.POST.get("matter_id")
    note.delete()
    redirect_url = f"/tasks/{task_id}/detail/"
    if matter_id:
        redirect_url += f"?matter_id={matter_id}"
    return redirect(redirect_url)


@login_required
@require_POST
def tasks_toggle_select(request, task_id):
    get_object_or_404(Task, pk=task_id)
    toggle_id(request, get_session_key("selected_tasks"), task_id)

    return selection_response(TASKS_TRIGGER)


@login_required
@require_POST
def tasks_select_all(request):
    visible_ids = [t.id for t in get_list_data(request)["objects"]]
    select_all_ids(request, get_session_key("selected_tasks"), visible_ids)

    return selection_response(TASKS_TRIGGER)


@login_required
@require_POST
def tasks_clear_selection(request):
    clear_selected_ids(request, get_session_key("selected_tasks"))

    return selection_response(TASKS_TRIGGER)


@login_required
def tasks_bulk_update(request):
    key = get_session_key("selected_tasks")
    selected_tasks = get_selected_ids(request, key)

    if not selected_tasks:
        return HttpResponse(status=400, content="No tasks selected.")

    if request.method == "POST":
        form = BulkTasksForm(request.POST)
        if form.is_valid():
            tasks = Task.objects.filter(id__in=selected_tasks)
            status = form.cleaned_data.get("status")
            importance = form.cleaned_data.get("importance")
            date_due = form.cleaned_data.get("date_due")
            user = form.cleaned_data.get("user")
            matter = form.cleaned_data.get("matter")

            for task in tasks:
                if status:
                    task.status = status

                if importance:
                    task.importance = int(importance)

                if date_due:
                    task.date_due = date_due

                if user:
                    task.user = user

                if matter:
                    task.matter = matter

                task.save()

            clear_selected_ids(request, key)

            return selection_response(TASKS_TRIGGER)

        return render(request, "tasks/bulk-update-modal.html", {"form": form})

    form = BulkTasksForm()

    return render(request, "tasks/bulk-update-modal.html", {"form": form})


@login_required
@require_POST
def tasks_bulk_set_due_date(request):
    """Set due date on selected tasks."""
    key = get_session_key("selected_tasks")
    selected_tasks = get_selected_ids(request, key)

    if not selected_tasks:
        return HttpResponse(status=400, content="No tasks selected.")

    date_due = request.POST.get("date_due")
    if date_due:
        Task.objects.filter(id__in=selected_tasks).update(date_due=date_due)
        clear_selected_ids(request, key)

    return selection_response(TASKS_TRIGGER)


@login_required
@require_POST
def tasks_bulk_clear_due_date(request):
    """Clear due dates on selected tasks."""
    key = get_session_key("selected_tasks")
    selected_tasks = get_selected_ids(request, key)

    if not selected_tasks:
        return HttpResponse(status=400, content="No tasks selected.")

    Task.objects.filter(id__in=selected_tasks).update(date_due=None)
    clear_selected_ids(request, key)

    return selection_response(TASKS_TRIGGER)


@login_required
@require_POST
def tasks_bulk_set_importance(request):
    """Set importance on selected tasks."""
    key = get_session_key("selected_tasks")
    selected_tasks = get_selected_ids(request, key)

    if not selected_tasks:
        return HttpResponse(status=400, content="No tasks selected.")

    importance = request.POST.get("importance")
    if importance:
        Task.objects.filter(id__in=selected_tasks).update(importance=int(importance))
        clear_selected_ids(request, key)

    return selection_response(TASKS_TRIGGER)


@login_required
@require_POST
def tasks_bulk_set_status(request):
    """Set status on selected tasks."""
    key = get_session_key("selected_tasks")
    selected_tasks = get_selected_ids(request, key)

    if not selected_tasks:
        return HttpResponse(status=400, content="No tasks selected.")

    status = request.POST.get("status")
    if status:
        tasks = Task.objects.filter(id__in=selected_tasks)
        if status == STATUS_COMPLETE:
            skipped = 0
            for task in tasks:
                if can_complete_task(task):
                    task.status = status
                    task.save()
                else:
                    skipped += 1
            if skipped:
                clear_selected_ids(request, key)
                response = selection_response(TASKS_TRIGGER)
                response["HX-Toast"] = json.dumps(
                    {
                        "type": "warning",
                        "message": f"{skipped} task(s) skipped — complete their checklists first.",
                    }
                )
                return response
        else:
            tasks.update(status=status)
        clear_selected_ids(request, key)

    return selection_response(TASKS_TRIGGER)


@login_required
@require_POST
def tasks_bulk_set_user(request):
    """Set user on selected tasks."""
    key = get_session_key("selected_tasks")
    selected_tasks = get_selected_ids(request, key)

    if not selected_tasks:
        return HttpResponse(status=400, content="No tasks selected.")

    user_id = request.POST.get("user")
    if user_id:
        user = get_object_or_404(CustomUser, pk=user_id)
        Task.objects.filter(id__in=selected_tasks).update(user=user)
        clear_selected_ids(request, key)

    return selection_response(TASKS_TRIGGER)


@login_required
@require_POST
def tasks_bulk_delete(request):
    key = get_session_key("selected_tasks")
    selected_tasks = get_selected_ids(request, key)

    if not selected_tasks:
        return HttpResponse(status=400, content="No tasks selected.")

    Task.objects.filter(id__in=selected_tasks).delete()
    clear_selected_ids(request, key)

    return selection_response(TASKS_TRIGGER)
