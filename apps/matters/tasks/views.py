from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.accounts.models import CustomUser
from apps.agenda.tasks.filter import TasksFilter
from apps.agenda.tasks.forms import TaskForm
from apps.agenda.tasks.models import Task
from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter


def get_matter_tasks_data(request, matter_id):
    """Get filtered task data for a specific matter"""
    matter = get_object_or_404(Matter, pk=matter_id)
    today = date.today()

    # Get filter data from session, but ensure it's scoped to this matter
    filter_data = request.session.get("matter_tasks_filter", {})

    # Always filter by the current matter
    filter_data["matter"] = matter_id

    if filter_data:
        filter_data = {
            **filter_data,
            "order_by": filter_data.get("order_by", "-priority"),
            "matter": matter_id,
        }
        filter = TasksFilter(filter_data)
        tasks = filter.qs
        user_id = filter_data.get("user")
        user_id = int(user_id) if user_id not in (None, "") else None
        focus = filter_data.get("focus")
    else:
        # Default filter for matter tasks - show all users and all focus by default
        default_filter = {
            "status": "Pending",
            "matter": matter_id,
            "order_by": "-priority",
            "user": None,  # All users
            "focus": "",  # All focus values
        }
        filter = TasksFilter(default_filter)
        tasks = filter.qs
        user_id = None
        focus = ""

    pagination = CustomPaginator(
        tasks, per_page=20, request=request, session_key="matter_tasks_pagination"
    )

    selected_user = None
    if user_id:
        selected_user = CustomUser.objects.filter(id=user_id).first()

    list_data = {
        "pagination": pagination,
        "session_key": "matter_tasks_pagination",
        "trigger_key": "matterTasksListChanged",
        "objects": pagination.get_object_list(),
        "matter": matter,
        "today": today,
        "users": CustomUser.objects.filter(is_active=True).order_by("username"),
        "user_id": user_id,
        "selected_user": selected_user.username.capitalize() if selected_user else None,
        "focus": focus,
        "filter_label": filter_data.get("filter_label", None) if filter_data else None,
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
            return HttpResponse(
                status=204, headers={"HX-Trigger": "matterTasksListChanged"}
            )
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
                "focus": focus,
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
def tasks_edit(request, id, task_id):
    """Edit task modal for a matter"""
    matter = get_object_or_404(Matter, pk=id)
    task = get_object_or_404(Task, pk=task_id, matter=matter)

    if request.method == "POST":
        form = TaskForm(request.POST, instance=task)
        if form.is_valid():
            task = form.save(commit=False)
            task.save()
            return HttpResponse(
                status=204, headers={"HX-Trigger": "matterTasksListChanged"}
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
    return HttpResponse(status=204, headers={"HX-Trigger": "matterTasksListChanged"})


@login_required
def tasks_filter(request, id):
    """Filter modal for matter tasks"""
    matter = get_object_or_404(Matter, pk=id)

    if request.method == "POST":
        # Store filter data in session with matter scope
        filter_data = request.POST.copy()
        filter_data["matter"] = id  # Ensure matter is always set
        request.session["matter_tasks_filter"] = filter_data
        return HttpResponse(
            status=204, headers={"HX-Trigger": "matterTasksListChanged"}
        )
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
    return HttpResponse(status=204, headers={"HX-Trigger": "matterTasksListChanged"})


@login_required
def tasks_filter_focus(request, id, focus):
    """Filter tasks by focus for a matter"""
    filter_data = request.session.get("matter_tasks_filter", {})
    filter_data["matter"] = id

    if focus == "All":
        focus = None

    filter_data["focus"] = focus
    request.session["matter_tasks_filter"] = filter_data
    return HttpResponse(status=204, headers={"HX-Trigger": "matterTasksListChanged"})


@login_required
def tasks_status(request, id, task_id):
    """Toggle task status for a matter"""
    matter = get_object_or_404(Matter, pk=id)
    task = get_object_or_404(Task, pk=task_id, matter=matter)

    if task.status == "Complete":
        task.status = "Pending"
    else:
        task.status = "Complete"
    task.save()
    return HttpResponse(status=204, headers={"HX-Trigger": "matterTasksListChanged"})


@login_required
def tasks_priority(request, id, task_id, priority):
    """Change task priority for a matter"""
    matter = get_object_or_404(Matter, pk=id)
    task = get_object_or_404(Task, pk=task_id, matter=matter)
    task.priority = priority
    task.save()
    return HttpResponse(status=204, headers={"HX-Trigger": "matterTasksListChanged"})


@login_required
def tasks_user(request, id, task_id, user_id):
    """Change task user for a matter"""
    matter = get_object_or_404(Matter, pk=id)
    task = get_object_or_404(Task, pk=task_id, matter=matter)
    user = get_object_or_404(CustomUser, pk=user_id)
    task.user = user
    task.save()
    return HttpResponse(status=204, headers={"HX-Trigger": "matterTasksListChanged"})


@login_required
def tasks_focus(request, id, task_id, focus):
    """Change task focus for a matter"""
    matter = get_object_or_404(Matter, pk=id)
    task = get_object_or_404(Task, pk=task_id, matter=matter)
    task.focus = focus
    task.save()
    return HttpResponse(status=204, headers={"HX-Trigger": "matterTasksListChanged"})


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
        return HttpResponse(
            status=204, headers={"HX-Trigger": "matterTasksListChanged"}
        )
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
    return HttpResponse(status=204, headers={"HX-Trigger": "matterTasksListChanged"})
