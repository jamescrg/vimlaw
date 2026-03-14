import json
from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.accounts.models import CustomUser
from apps.management.pagination import CustomPaginator
from apps.management.selection import (
    all_visible_selected,
    clear_selected_ids,
    get_selected_ids,
    get_session_key,
    select_all_ids,
    selection_response,
    toggle_id,
)
from apps.matters.models import Matter
from apps.tasks.filter import TasksFilter
from apps.tasks.forms import BulkTasksForm, TaskForm
from apps.tasks.models import (
    Checklist,
    Task,
    TaskNote,
    UserChecklistView,
    UserTaskNoteView,
    can_complete_task,
)

TASKS_TRIGGER = "tasksListChanged"


def get_matter_tasks_data(request, matter_id):
    """Get filtered task data for a specific matter"""
    matter = get_object_or_404(Matter, pk=matter_id)
    today = date.today()

    # Get filter data from session, but ensure it's scoped to this matter
    filter_data = request.session.get("matter_tasks_filter", {})

    # Check if we have meaningful filter data (more than just the matter key)
    has_existing_filter = any(key != "matter" for key in filter_data.keys())

    # Always start with a queryset filtered by the current matter
    matter_queryset = Task.objects.filter(matter=matter)

    if has_existing_filter:
        filter_data = {
            **filter_data,
            "status": filter_data.get("status", "Pending"),
            "order_by": filter_data.get("order_by", "priority"),
            "matter": matter_id,
        }
        filter = TasksFilter(filter_data, queryset=matter_queryset)
        tasks = filter.qs
        user_id = filter_data.get("user")
        user_id = int(user_id) if user_id not in (None, "") else None
        focus = filter_data.get("focus")
    else:
        # Default filter for matter tasks - show pending tasks, all users and all focus by default
        default_filter = {
            "status": "Pending",
            "matter": matter_id,
            "order_by": "priority",
            "user": None,  # All users
            "focus": "",  # All focus values
        }
        filter = TasksFilter(default_filter, queryset=matter_queryset)
        tasks = filter.qs
        user_id = None
        focus = ""

    # Force-show newly created tasks at the top regardless of filters
    new_task_ids = request.session.pop("new_task_ids", [])

    # Exclude new tasks from main queryset to avoid duplicates
    if new_task_ids:
        tasks = tasks.exclude(id__in=new_task_ids)

    pagination = CustomPaginator(
        tasks, per_page=20, request=request, session_key="matter_tasks_pagination"
    )

    # Get user's note view history for badge notification system
    user_note_views = UserTaskNoteView.objects.filter(user=request.user).values(
        "task_id", "last_viewed_at"
    )
    view_times = {v["task_id"]: v["last_viewed_at"] for v in user_note_views}

    # Prepend new tasks to the top of the page
    if new_task_ids:
        new_tasks = list(Task.objects.filter(id__in=new_task_ids, matter=matter))
        task_list = new_tasks + list(pagination.get_object_list())
    else:
        task_list = pagination.get_object_list()

    # Bulk-prefetch checklists to avoid N+1
    task_ids = [t.id for t in task_list]
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
        task.has_notes = task.notes.exists()
        if task.has_notes:
            last_viewed = view_times.get(task.id)
            if last_viewed:
                # Check if there are notes created after last view by other users
                task.has_new_notes = (
                    TaskNote.objects.filter(task=task, created_at__gt=last_viewed)
                    .exclude(user=request.user)
                    .exists()
                )
            else:
                # Never viewed - show as new if there are notes by other users
                task.has_new_notes = (
                    TaskNote.objects.filter(task=task)
                    .exclude(user=request.user)
                    .exists()
                )
        else:
            task.has_new_notes = False

        cl = checklists_by_task.get(task.id)
        if cl:
            task.has_checklist = True
            items = cl.items.all()
            task.checklist_total = len(items)
            task.checklist_done = sum(1 for i in items if i.is_complete)
            task.checklist_complete = task.checklist_done == task.checklist_total
            task.has_unviewed_checklist = task.id not in viewed_checklist_task_ids
        else:
            task.has_checklist = False
            task.has_unviewed_checklist = False

    selected_user = None
    if user_id:
        selected_user = CustomUser.objects.filter(id=user_id).first()

    priority_value = filter_data.get("priority") if filter_data else None

    # Get current order and strip leading '-' for comparison
    current_order = (
        filter_data.get("order_by", "priority") if filter_data else "priority"
    )
    current_order = current_order.lstrip("-")

    # Selection state
    selected_session_key = get_session_key("selected_tasks", matter_id)
    selected_tasks = get_selected_ids(request, selected_session_key)
    visible_ids = [task.id for task in task_list]
    all_selected = all_visible_selected(selected_tasks, visible_ids)

    list_data = {
        "pagination": pagination,
        "session_key": "matter_tasks_pagination",
        "trigger_key": TASKS_TRIGGER,
        "objects": task_list,
        "matter": matter,
        "today": today,
        "users": CustomUser.objects.filter(is_active=True).order_by("username"),
        "user_id": user_id,
        "selected_user": selected_user.username.capitalize() if selected_user else None,
        "priorities": list(range(1, 11)),
        "priority_value": priority_value,
        "selected_priority": f"Priority ≤ {priority_value}" if priority_value else "",
        "focus": focus,
        "filter_label": filter_data.get("filter_label", None) if filter_data else None,
        "current_order": current_order,
        "selected_tasks": selected_tasks,
        "all_selected": all_selected,
        "new_task_ids": new_task_ids,
    }

    return list_data


@login_required
def tasks_index(request, id):
    """Main tasks view for a matter"""
    matter = get_object_or_404(Matter, pk=id)
    task_data = get_matter_tasks_data(request, id)

    context = {
        "app": "matters",
        "subapp": "tasks",
        "matter": matter,
    } | task_data

    return render(request, "matters/tasks/main.html", context)


@login_required
def tasks_list(request, id):
    """Tasks list view for a matter"""
    task_data = get_matter_tasks_data(request, id)
    return render(request, "matters/tasks/list.html", task_data)


@login_required
def tasks_add(request, id):
    """Add task modal for a matter"""
    matter = get_object_or_404(Matter, pk=id)

    if request.method == "POST":
        form = TaskForm(request.POST, use_required_attribute=False)
        if form.is_valid():
            task = form.save(commit=False)
            task.status = "Pending"
            task.matter = matter  # Automatically assign to the current matter
            task.save()

            # Store new task ID for force-show in filtered lists
            new_task_ids = request.session.get("new_task_ids", [])
            new_task_ids.append(task.id)
            request.session["new_task_ids"] = new_task_ids

            return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})
    else:
        # Get the currently filtered user if available
        filter_data = request.session.get("matter_tasks_filter", {})
        user_id = filter_data.get("user")
        focus = filter_data.get("focus")

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
                "matter": matter,
                "date_due": date.today(),
                "focus": focus if focus else "Long Term",  # Default to Long Term
            },
            use_required_attribute=False,
        )

    # Set the matter to readonly since we're in a matter context
    form.fields["matter"].widget.attrs["readonly"] = True
    form.fields["matter"].queryset = Matter.objects.filter(id=matter.id)
    users = CustomUser.objects.filter(is_active=True).order_by("username")
    form.fields["user"].queryset = users

    context = {
        "app": "matters",
        "subapp": "tasks",
        "matter": matter,
        "edit": False,
        "add": True,
        "form": form,
    }

    return render(request, "matters/tasks/form.html", context)


@login_required
def tasks_add_quick(request, id):
    matter = get_object_or_404(Matter, pk=id)
    task = Task()

    # prevent creation of tasks without a description
    if not request.POST["description"]:
        return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})

    # get filter values to auto populate task properties
    filter_data = request.session.get("matter_tasks_filter", {})

    # set task description and some property values
    task.description = request.POST["description"]
    task.status = "Pending"
    task.date_due = date.today()
    task.matter = matter  # Always assign to the current matter

    # auto populate priority from filter
    filter_priority = filter_data.get("priority")
    if filter_priority and int(filter_priority) != 0:
        task.priority = int(filter_priority)
    else:
        task.priority = 5

    # auto populate the user
    user_id = filter_data.get("user", None)
    if not user_id:
        user_id = request.user.id
    task.user = CustomUser.objects.filter(pk=int(user_id)).get()

    # auto populate the focus
    focus = filter_data.get("focus", None)
    if focus:
        task.focus = focus
    else:
        task.focus = "Long Term"

    task.save()

    # Store new task ID for force-show in filtered lists
    new_task_ids = request.session.get("new_task_ids", [])
    new_task_ids.append(task.id)
    request.session["new_task_ids"] = new_task_ids

    return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})


@login_required
def tasks_edit(request, id, task_id):
    """Edit task modal for a matter"""
    matter = get_object_or_404(Matter, pk=id)
    task = get_object_or_404(Task, pk=task_id, matter=matter)

    if request.method == "POST":
        form = TaskForm(request.POST, instance=task)
        if form.is_valid():
            task = form.save(commit=False)
            if task.status == "Complete" and not can_complete_task(task):
                form.add_error(
                    "status",
                    "Please complete all checklist items before marking this task as done.",
                )
            else:
                task.save()
                return HttpResponse(
                    status=204, headers={"HX-Trigger": "tasksListChanged"}
                )
    else:
        form = TaskForm(instance=task)

    # Set the matter to readonly since we're in a matter context
    form.fields["matter"].widget.attrs["readonly"] = True
    form.fields["matter"].queryset = Matter.objects.filter(id=matter.id)
    users = CustomUser.objects.filter(is_active=True).order_by("username")
    form.fields["user"].queryset = users

    context = {
        "app": "matters",
        "subapp": "tasks",
        "matter": matter,
        "edit": True,
        "task": task,
        "form": form,
    }

    return render(request, "matters/tasks/form.html", context)


@login_required
def tasks_delete(request, id, task_id):
    """Delete task for a matter"""
    matter = get_object_or_404(Matter, pk=id)
    task = get_object_or_404(Task, pk=task_id, matter=matter)
    task.delete()
    return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})


@login_required
def tasks_filter(request, id):
    """Filter modal for matter tasks"""
    matter = get_object_or_404(Matter, pk=id)

    if request.method == "POST":
        # Store filter data in session with matter scope
        filter_data = request.POST.copy()
        filter_data["matter"] = id  # Ensure matter is always set
        request.session["matter_tasks_filter"] = filter_data
        return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})
    else:
        filter_data = request.session.get("matter_tasks_filter", {})
        filter_data["matter"] = id  # Ensure matter is always set

        if filter_data:
            # Create a queryset filtered by matter
            queryset = Task.objects.filter(matter=matter)
            filter = TasksFilter(filter_data, queryset=queryset)
        else:
            default_filter = {
                "status": "Pending",
                "matter": id,
                "order_by": "date_due",
                "user": None,  # All users by default
                "focus": "",  # All focus by default
            }
            queryset = Task.objects.filter(matter=matter)
            filter = TasksFilter(default_filter, queryset=queryset)

        return render(
            request, "matters/tasks/filter.html", {"filter": filter, "matter": matter}
        )


@login_required
def tasks_filter_user(request, id, user_id):
    """Filter tasks by user for a matter"""
    filter_data = request.session.get("matter_tasks_filter", {})
    filter_data["matter"] = id
    filter_data["user"] = user_id if user_id != 0 else None

    request.session["matter_tasks_filter"] = filter_data
    return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})


@login_required
def tasks_filter_focus(request, id, focus):
    """Filter tasks by focus for a matter"""
    filter_data = request.session.get("matter_tasks_filter", {})
    filter_data["matter"] = id

    if focus == "All":
        focus = None

    filter_data["focus"] = focus
    request.session["matter_tasks_filter"] = filter_data
    return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})


@login_required
def tasks_filter_priority(request, id, priority_value):
    """Filter tasks by priority for a matter"""
    filter_data = request.session.get("matter_tasks_filter", {})
    filter_data["matter"] = id
    # Set to None when 0 (All) is selected, otherwise use the value
    filter_data["priority"] = None if priority_value == 0 else priority_value

    request.session["matter_tasks_filter"] = filter_data
    return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})


@login_required
def tasks_status(request, id, task_id):
    """Toggle task status for a matter"""
    matter = get_object_or_404(Matter, pk=id)
    task = get_object_or_404(Task, pk=task_id, matter=matter)

    if task.status == "Complete":
        task.status = "Pending"
    else:
        if not can_complete_task(task):
            response = HttpResponse(status=204)
            response["HX-Toast"] = json.dumps(
                {
                    "type": "items incomplete",
                    "message": "Please complete all checklist items before marking this task as done.",
                }
            )
            return response
        task.status = "Complete"
    task.save()
    return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})


@login_required
def tasks_set_status(request, id, task_id, status):
    """Set task status for a matter"""
    matter = get_object_or_404(Matter, pk=id)
    task = get_object_or_404(Task, pk=task_id, matter=matter)
    if status == "Complete" and not can_complete_task(task):
        response = HttpResponse(status=204)
        response["HX-Toast"] = json.dumps(
            {
                "type": "warning",
                "message": "Please complete all checklist items before marking this task as done.",
            }
        )
        return response
    task.status = status
    task.save()
    return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})


@login_required
def tasks_priority(request, id, task_id, priority):
    """Change task priority for a matter"""
    matter = get_object_or_404(Matter, pk=id)
    task = get_object_or_404(Task, pk=task_id, matter=matter)
    task.priority = priority
    task.save()
    return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})


@login_required
def tasks_user(request, id, task_id, user_id):
    """Change task user for a matter"""
    matter = get_object_or_404(Matter, pk=id)
    task = get_object_or_404(Task, pk=task_id, matter=matter)
    user = get_object_or_404(CustomUser, pk=user_id)
    task.user = user
    task.save()
    return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})


@login_required
def tasks_focus(request, id, task_id, focus):
    """Change task focus for a matter"""
    matter = get_object_or_404(Matter, pk=id)
    task = get_object_or_404(Task, pk=task_id, matter=matter)
    task.focus = focus
    task.save()
    return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})


@login_required
def tasks_date(request, id, task_id):
    """Edit task date for a matter"""
    matter = get_object_or_404(Matter, pk=id)
    task = get_object_or_404(Task, pk=task_id, matter=matter)

    if request.method == "POST":
        from datetime import datetime

        try:
            date_due = datetime.strptime(request.POST["date_due"], "%Y-%m-%d")
        except ValueError:
            date_due = None
        task.date_due = date_due
        task.save()
        return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})
    else:
        context = {
            "task": task,
            "matter": matter,
        }
        return render(request, "matters/tasks/date-edit.html", context)


@login_required
def tasks_filter_sort(request, id, order):
    """Sort tasks for a matter"""
    filter_data = request.session.get("matter_tasks_filter", {})
    filter_data["matter"] = id

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["matter_tasks_filter"] = filter_data

    # Auto-initialize custom_order values when switching to custom_order mode
    if new_order == "custom_order":
        matter = get_object_or_404(Matter, pk=id)
        # Check if this matter's tasks have any null custom_order values
        matter_tasks = Task.objects.filter(matter=matter, custom_order__isnull=True)
        if matter_tasks.exists():
            # Get all matter's tasks in current display order using date_due ordering
            temp_filter_data = {**filter_data, "order_by": "date_due"}
            temp_filter = TasksFilter(
                temp_filter_data, queryset=Task.objects.filter(matter=matter)
            )
            all_tasks = list(temp_filter.qs)

            # Assign sequential custom_order values
            tasks_to_update = []
            for index, task in enumerate(all_tasks):
                if task.custom_order is None:
                    task.custom_order = Decimal(str(index + 1))
                    tasks_to_update.append(task)

            # Bulk update
            if tasks_to_update:
                Task.objects.bulk_update(tasks_to_update, ["custom_order"])

    return HttpResponse(status=204, headers={"HX-Trigger": TASKS_TRIGGER})


@login_required
@require_POST
def tasks_toggle_select(request, id, task_id):
    """Toggle selection of a single task."""
    get_object_or_404(Task, pk=task_id, matter_id=id)

    key = get_session_key("selected_tasks", id)
    toggle_id(request, key, task_id)

    return selection_response(TASKS_TRIGGER)


@login_required
@require_POST
def tasks_select_all(request, id):
    """Toggle select-all for visible tasks."""
    key = get_session_key("selected_tasks", id)

    visible_ids = [t.id for t in get_matter_tasks_data(request, id)["objects"]]
    select_all_ids(request, key, visible_ids)

    return selection_response(TASKS_TRIGGER)


@login_required
@require_POST
def tasks_clear_selection(request, id):
    """Clear all task selections for this matter."""
    clear_selected_ids(request, get_session_key("selected_tasks", id))

    return selection_response(TASKS_TRIGGER)


@login_required
def tasks_bulk_update(request, id):
    """Bulk update selected tasks."""
    matter = get_object_or_404(Matter, pk=id)

    key = get_session_key("selected_tasks", id)
    selected_tasks = get_selected_ids(request, key)

    if not selected_tasks:
        return HttpResponse(status=400, content="No tasks selected.")

    if request.method == "POST":
        form = BulkTasksForm(request.POST)

        if form.is_valid():
            tasks = Task.objects.filter(id__in=selected_tasks, matter=matter)
            status = form.cleaned_data.get("status")
            priority = form.cleaned_data.get("priority")
            date_due = form.cleaned_data.get("date_due")
            user = form.cleaned_data.get("user")
            new_matter = form.cleaned_data.get("matter")

            for task in tasks:
                if status:
                    task.status = status

                if priority:
                    task.priority = int(priority)

                if date_due:
                    task.date_due = date_due

                if user:
                    task.user = user

                if new_matter:
                    task.matter = new_matter

                task.save()

            clear_selected_ids(request, key)
            return selection_response(TASKS_TRIGGER)

        return render(
            request,
            "matters/tasks/bulk-update-modal.html",
            {"form": form, "matter": matter},
        )

    form = BulkTasksForm()
    return render(
        request,
        "matters/tasks/bulk-update-modal.html",
        {"form": form, "matter": matter},
    )


@login_required
@require_POST
def tasks_bulk_set_due_date(request, id):
    """Set due date on selected tasks."""
    key = get_session_key("selected_tasks", id)
    selected_tasks = get_selected_ids(request, key)

    if not selected_tasks:
        return HttpResponse(status=400, content="No tasks selected.")

    date_due = request.POST.get("date_due")
    if date_due:
        Task.objects.filter(id__in=selected_tasks, matter_id=id).update(
            date_due=date_due
        )
        clear_selected_ids(request, key)

    return selection_response(TASKS_TRIGGER)


@login_required
@require_POST
def tasks_bulk_clear_due_date(request, id):
    """Clear due dates on selected tasks."""
    key = get_session_key("selected_tasks", id)
    selected_tasks = get_selected_ids(request, key)

    if not selected_tasks:
        return HttpResponse(status=400, content="No tasks selected.")

    Task.objects.filter(id__in=selected_tasks, matter_id=id).update(date_due=None)
    clear_selected_ids(request, key)

    return selection_response(TASKS_TRIGGER)


@login_required
@require_POST
def tasks_bulk_set_priority(request, id):
    """Set priority on selected tasks."""
    key = get_session_key("selected_tasks", id)
    selected_tasks = get_selected_ids(request, key)

    if not selected_tasks:
        return HttpResponse(status=400, content="No tasks selected.")

    priority = request.POST.get("priority")
    if priority:
        Task.objects.filter(id__in=selected_tasks, matter_id=id).update(
            priority=int(priority)
        )
        clear_selected_ids(request, key)

    return selection_response(TASKS_TRIGGER)


@login_required
@require_POST
def tasks_bulk_set_status(request, id):
    """Set status on selected tasks."""
    key = get_session_key("selected_tasks", id)
    selected_tasks = get_selected_ids(request, key)

    if not selected_tasks:
        return HttpResponse(status=400, content="No tasks selected.")

    status = request.POST.get("status")
    if status:
        tasks = Task.objects.filter(id__in=selected_tasks, matter_id=id)
        if status == "Complete":
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
def tasks_bulk_set_user(request, id):
    """Set user on selected tasks."""
    key = get_session_key("selected_tasks", id)
    selected_tasks = get_selected_ids(request, key)

    if not selected_tasks:
        return HttpResponse(status=400, content="No tasks selected.")

    user_id = request.POST.get("user")
    if user_id:
        user = get_object_or_404(CustomUser, pk=user_id)
        Task.objects.filter(id__in=selected_tasks, matter_id=id).update(user=user)
        clear_selected_ids(request, key)

    return selection_response(TASKS_TRIGGER)


@login_required
@require_POST
def tasks_bulk_delete(request, id):
    """Bulk delete selected tasks."""
    key = get_session_key("selected_tasks", id)
    selected_tasks = get_selected_ids(request, key)

    if not selected_tasks:
        return HttpResponse(status=400, content="No tasks selected.")

    Task.objects.filter(id__in=selected_tasks, matter_id=id).delete()
    clear_selected_ids(request, key)

    return selection_response(TASKS_TRIGGER)
