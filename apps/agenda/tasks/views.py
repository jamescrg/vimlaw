from datetime import date, datetime, timedelta

import markdown
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import CustomUser
from apps.agenda.tasks.filter import TasksFilter
from apps.agenda.tasks.forms import BulkTasksForm, TaskForm, TaskNoteForm
from apps.agenda.tasks.models import Task, TaskNote, UserTaskNoteView
from apps.agenda.tasks.services import process_quick_task_description
from apps.agenda.tasks.tasks import get_list_data
from apps.management.selection import (
    clear_selected_ids,
    get_selected_ids,
    get_session_key,
    select_all_ids,
    selection_response,
    toggle_id,
)
from apps.matters.models import Matter

TASKS_TRIGGER = "tasksListChanged"


@login_required
def tasks_index(request):
    request.session["agenda_last_tab"] = "tasks"
    context = get_list_data(request)
    context = context | {
        "app": "agenda",
        "subapp": "tasks",
    }
    return render(request, "agenda/tasks/tasks.html", context)


@login_required
def tasks_list(request):
    context = get_list_data(request)
    return render(request, "agenda/tasks/list.html", context)


@login_required
def tasks_select(request):
    return redirect("agenda:tasks-index")


@login_required
def tasks_add(request):
    if request.method == "POST":
        form = TaskForm(request.POST, use_required_attribute=False)
        if form.is_valid():
            task = form.save(commit=False)
            task.status = "Pending"
            task.save()
            if task.matter:
                request.session["tasks_matter"] = task.matter.id
            return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})

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
            },
            use_required_attribute=False,
        )

    matters = Matter.objects.filter(status__in=["Pending", "Open"]).order_by("name")
    form.fields["matter"].queryset = matters
    form.fields["matter"].empty_label = "Admin"
    users = CustomUser.objects.filter(is_active=True).order_by("username")
    form.fields["user"].queryset = users

    context = {
        "app": "agenda",
        "edit": False,
        "add": True,
        "form": form,
    }

    return render(request, "agenda/tasks/form.html", context)


@login_required
def tasks_add_quick(request):
    task = Task()

    # prevent creation of tasks without a description
    if not request.POST["description"]:
        return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})

    # Process description with intelligent matter matching
    last_matter_id = request.session.get("last_quick_task_matter")
    description, matched_matter, use_smart_matching = process_quick_task_description(
        request.POST["description"], last_matter_id
    )

    # Prevent creation of tasks with empty description after processing
    if not description.strip():
        return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})

    # set task description and some property values
    task.description = description
    task.status = "Pending"
    task.priority = 1

    # get filter values to auto populate task properties
    filter_data = request.session.get("tasks_filter", {})

    # auto populate the user
    user_id = filter_data.get("user", None)
    if not user_id:
        user_id = request.user.id
    task.user = CustomUser.objects.filter(pk=int(user_id)).get()

    # Set matter: use smart matching if applicable, otherwise use filter matter
    if use_smart_matching:
        task.matter = matched_matter
    else:
        matter_id = filter_data.get("matter", None)
        if matter_id:
            task.matter = Matter.objects.filter(pk=int(matter_id)).get()

    task.save()

    # Store the matter ID (or None for Admin) in session for next quick task
    if task.matter:
        request.session["last_quick_task_matter"] = task.matter.id
    else:
        request.session["last_quick_task_matter"] = None

    return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})


@login_required
def tasks_edit(request, id):
    task = get_object_or_404(Task, pk=id)

    if request.method == "POST":
        form = TaskForm(request.POST, instance=task)
        if form.is_valid():
            task = form.save(commit=False)
            task.save()
            return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})

    else:
        form = TaskForm(instance=task)

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
        "app": "agenda",
        "edit": True,
        "task": task,
        "form": form,
    }

    return render(request, "agenda/tasks/form.html", context)


@login_required
def tasks_delete(request, id):
    entry = get_object_or_404(Task, pk=id)
    entry.delete()
    return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})


@login_required
def tasks_filter(request, user=None):
    if request.method == "POST":
        # Convert QueryDict to regular dict, excluding CSRF token
        filter_data = {
            key: value
            for key, value in request.POST.items()
            if key != "csrfmiddlewaretoken"
        }
        request.session["tasks_filter"] = filter_data
        return HttpResponse(status=204, headers={"HX-Trigger": "tasksListChanged"})

    else:
        filter_data = request.session.get("tasks_filter", {})

        if filter_data:
            # Sanitize filter data to remove invalid values
            sanitized_data = filter_data.copy()

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

            filter = TasksFilter(sanitized_data, queryset=Task.objects.all())

            # If the filter is invalid, reset to defaults
            if not filter.form.is_valid():
                default_filter = {
                    "status": "Pending",
                    "matter": None,
                    "order_by": "date_due",
                    "user": request.user.id,
                }
                filter = TasksFilter(default_filter, queryset=Task.objects.all())
        else:
            default_filter = {
                "status": "Pending",
                "matter": None,
                "order_by": "date_due",
                "user": request.user.id,
            }

            filter = TasksFilter(default_filter, queryset=Task.objects.all())

        return render(request, "agenda/tasks/filter.html", {"filter": filter})


@login_required
def tasks_filter_quick(request, quick_filter):
    end_of_week = date.today() + timedelta(days=7)
    end_of_week = end_of_week.strftime("%Y-%m-%d")
    filter_data = request.session.get("tasks_filter", {})
    quick_filters = {
        "today": {
            "filter_label": "today",
            "status": "Pending",
            "date_due_max": date.today().strftime("%Y-%m-%d"),
            "matter": filter_data.get("matter"),
            "user": filter_data.get("user"),
            "order_by": filter_data.get("order_by"),
        },
        "week": {
            "filter_label": "week",
            "status": "Pending",
            "date_due_max": end_of_week,
            "matter": filter_data.get("matter"),
            "user": filter_data.get("user"),
            "order_by": filter_data.get("order_by"),
        },
    }
    filter_data = {}
    for key, val in quick_filters[quick_filter].items():
        filter_data[key] = val
    request.session["tasks_filter"] = filter_data
    request.session.modified = True
    return redirect("agenda:tasks-list")


@login_required
def tasks_filter_matter(request, matter_id):
    filter_data = request.session.get("tasks_filter", {})
    filter_data["matter"] = matter_id

    request.session["tasks_filter"] = filter_data

    return redirect("agenda:tasks-list")


@login_required
def tasks_filter_user(request, user_id):
    filter_data = request.session.get("tasks_filter", {})
    filter_data["user"] = user_id

    request.session["tasks_filter"] = filter_data

    return redirect("agenda:tasks-list")


@login_required
def tasks_filter_priority(request, priority_value):
    filter_data = request.session.get("tasks_filter", {})
    # Set to empty string when 0 (All) is selected, otherwise use the value
    filter_data["priority"] = "" if priority_value == 0 else priority_value

    request.session["tasks_filter"] = filter_data

    return redirect("agenda:tasks-list")


@login_required
def tasks_filter_default(request):
    filter_data = {
        "filter_label": "default",
        "status": "Pending",
        "date_due_max": None,
        "date_due_min": None,
        "matter": None,
        "user": request.user.id,
        "order_by": "priority",
    }
    request.session["tasks_filter"] = filter_data
    request.session.modified = True
    if request.headers.get("HX-Request"):
        return redirect("agenda:tasks-list")
    return redirect("agenda:tasks-index")


@login_required
def tasks_status(request, id):
    task = get_object_or_404(Task, pk=id)
    if task.status == "Complete":
        task.status = "Pending"
    else:
        task.status = "Complete"
    task.save()
    return redirect("agenda:tasks-list")


@login_required
def tasks_set_status(request, task_id, status):
    task = get_object_or_404(Task, pk=task_id)
    task.status = status
    task.save()
    return redirect("agenda:tasks-list")


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
    return render(request, "agenda/tasks/change-user.html", context)


@login_required
def tasks_priority(request, task_id, priority):
    task = get_object_or_404(Task, pk=task_id)
    task.priority = priority
    task.save()
    return redirect("agenda:tasks-list")


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
        return redirect("agenda:tasks-list")

    else:
        context = {
            "task": task,
        }
        return render(request, "agenda/tasks/date-edit.html", context)


@login_required
def tasks_user(request, task_id, user):
    task = get_object_or_404(Task, pk=task_id)
    user = get_object_or_404(CustomUser, pk=user)
    task.user = user
    task.save()
    return redirect("agenda:tasks-list")


@login_required
def tasks_matter(request, task_id, matter_id):
    task = get_object_or_404(Task, pk=task_id)
    if matter_id == 0:
        task.matter = None
    else:
        matter = get_object_or_404(Matter, pk=matter_id)
        task.matter = matter
    task.save()
    return redirect("agenda:tasks-list")


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

    return redirect("agenda:tasks-list")


@login_required
def clear_tasks(request):
    # Delete all the tasks from the filter that are marked as complete
    filter_data = request.session.get("tasks_filter", {})
    filter = TasksFilter(filter_data)
    filter.qs.filter(status="Complete").delete()
    return redirect("agenda:tasks-list")


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
            redirect_url = f"/agenda/tasks/{task.id}/detail/"
            if matter_id:
                redirect_url += f"?matter_id={matter_id}"
            return redirect(redirect_url)
    else:
        form = TaskNoteForm(
            initial={
                "date": date.today(),
                "time": datetime.now().strftime("%H:%M"),
            },
            use_required_attribute=False,
        )

    action = f"/agenda/tasks/{id}/add-note/"
    if matter_id:
        action += f"?matter_id={matter_id}"

    context = {
        "task": task,
        "form": form,
        "edit": False,
        "action": action,
        "matter_id": matter_id,
    }
    return render(request, "agenda/tasks/form_note.html", context)


@login_required
def tasks_detail(request, id):
    task = get_object_or_404(Task, pk=id)
    notes = task.notes.all()
    matter_id = request.GET.get("matter_id")

    # Track view for badge notification system
    UserTaskNoteView.objects.update_or_create(
        user=request.user,
        task=task,
        # last_viewed_at auto-updates with auto_now=True
    )

    # Process markdown in note details
    for note in notes:
        if note.details:
            note.details = markdown.markdown(note.details)

    context = {
        "task": task,
        "notes": notes,
        "matter_id": matter_id,
    }
    return render(request, "agenda/tasks/detail.html", context)


@login_required
def tasks_edit_note(request, id):
    note = get_object_or_404(TaskNote, pk=id)
    matter_id = request.GET.get("matter_id") or request.POST.get("matter_id")

    if request.method == "POST":
        form = TaskNoteForm(request.POST, instance=note, use_required_attribute=False)
        if form.is_valid():
            form.save()
            redirect_url = f"/agenda/tasks/{note.task.id}/detail/"
            if matter_id:
                redirect_url += f"?matter_id={matter_id}"
            return redirect(redirect_url)
    else:
        form = TaskNoteForm(instance=note, use_required_attribute=False)

    action = f"/agenda/tasks/note/{id}/edit/"
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
    return render(request, "agenda/tasks/form_note.html", context)


@login_required
def tasks_delete_note(request, id):
    note = get_object_or_404(TaskNote, pk=id)
    task_id = note.task.id
    matter_id = request.GET.get("matter_id") or request.POST.get("matter_id")
    note.delete()
    redirect_url = f"/agenda/tasks/{task_id}/detail/"
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
            priority = form.cleaned_data.get("priority")
            date_due = form.cleaned_data.get("date_due")
            user = form.cleaned_data.get("user")
            matter = form.cleaned_data.get("matter")

            for task in tasks:
                if status:
                    task.status = status

                if priority:
                    task.priority = int(priority)

                if date_due:
                    task.date_due = date_due

                if user:
                    task.user = user

                if matter:
                    task.matter = matter

                task.save()

            clear_selected_ids(request, key)

            return selection_response(TASKS_TRIGGER)

        return render(request, "agenda/tasks/bulk-update-modal.html", {"form": form})

    form = BulkTasksForm()

    return render(request, "agenda/tasks/bulk-update-modal.html", {"form": form})


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
