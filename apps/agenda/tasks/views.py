from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import CustomUser
from apps.agenda.tasks.filter import TasksFilter
from apps.agenda.tasks.forms import TaskForm
from apps.agenda.tasks.models import Task
from apps.agenda.tasks.tasks import get_table_data
from apps.matters.models import Matter


@login_required
def tasks_list(request):

    # check whether events have been hidden
    show_events = request.session.get("show_events", True)
    if show_events:
        return redirect("/events")

    # if events are hidden, check the date they were hidden
    # if that date is less than today, show them
    else:
        today = date.today()
        timestamp = int(request.session.get("hide_expire"))
        old_date = date.fromtimestamp(timestamp)
        if today > old_date:
            show_events = True
            request.session["show_events"] = True
            return redirect("/events")

    # save the currently selected matter in the add task form
    # so multiple tasks can quickly be added to a matter
    tasks_matter = request.session.get("tasks_matter")

    context = {
        "app": "agenda",
        "subapp": "tasks",
        "show_events": show_events,
        "tasks_matter": tasks_matter,
        "today": today,
    }

    return render(request, "agenda/tasks/list.html", context)


@login_required
def tasks_select(request):
    request.session["show_events"] = False
    request.session["hide_expire"] = date.today().strftime("%s")
    return redirect("/agenda")


@login_required
def tasks_add(request):

    if request.method == "POST":
        form = TaskForm(request.POST)
        if form.is_valid():

            task = form.save(commit=False)
            filter_data = request.session.get("tasks_filter", {})
            user_id = filter_data.get("user", None)
            if not user_id:
                user_id = request.user.id
            task.user = CustomUser.objects.filter(pk=int(user_id)).get()
            task.status = "Pending"
            task.save()
            return HttpResponse(status=204, headers={"HX-Trigger": "taskTableChanged"})
    else:
        form = TaskForm()

    matters = Matter.objects.filter(status="Open").order_by("name")
    form.fields["matter"].queryset = matters

    context = {
        "app": "agenda",
        "edit": False,
        "add": True,
        "form": form,
    }

    return render(request, "agenda/tasks/form.html", context)


@login_required
def tasks_edit(request, id):

    task = get_object_or_404(Task, pk=id)

    if request.method == "POST":

        form = TaskForm(request.POST, instance=task)
        if form.is_valid():
            task = form.save(commit=False)
            task.save()
            return HttpResponse(status=204, headers={"HX-Trigger": "taskTableChanged"})

    else:
        form = TaskForm(instance=task)

    # pull the list of matters
    matter_list = Matter.objects.filter(status="Open").order_by("name")

    # make sure the matter associated with the event is in the list
    # if not, add it
    # this ensures the matter is available in the form select element
    # even when the matter is closed
    if task.matter and task.matter not in matter_list:
        matter_list |= Matter.objects.filter(pk=task.matter.id)
    form.fields["matter"].queryset = matter_list

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
    return redirect("/agenda")


@login_required
def tasks_filter(request, user=None):
    if request.method == "POST":
        request.session["tasks_filter"] = request.POST
        return redirect("/agenda")

    else:
        filter_data = request.session.get("tasks_filter", {})
        filter = TasksFilter(filter_data, queryset=Task.objects.all())
        return render(request, "agenda/tasks/filter.html", {"filter": filter})


@login_required
def tasks_filter_quick(request, quick_filter):
    quick_filters = {
        "pending": {
            "status": "Pending",
            "date_due": "",
            "matter": None,
            "user": None,
            "order_by": "date",
        },
    }
    filter_data = {}
    for key, val in quick_filters[quick_filter].items():
        filter_data[key] = val
    request.session["tasks_filter"] = filter_data
    request.session.modified = True
    return redirect("agenda:tasks-list")


@login_required
def tasks_filter_user(request):
    filter_data = request.session.get("tasks_filter", {})
    user = request.POST.get("user")
    filter_data["user"] = user
    request.session["tasks_filter"] = filter_data
    return redirect("agenda:tasks-list")


@login_required
def tasks_status(request, id):
    task = get_object_or_404(Task, pk=id)
    if task.status == "Complete":
        task.status = "Pending"
    else:
        task.status = "Complete"
    task.save()
    context = {
        "task": task,
    }
    return render(request, "agenda/tasks/status.html", context)


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
def tasks_filter_sort(request, order):
    filter_data = request.session.get("tasks_filter", {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["tasks_filter"] = filter_data

    context = get_table_data(request)
    return render(request, "agenda/tasks/table.html", context)


@login_required
def clear_tasks(request):
    filter_data = request.session.get("tasks_filter", {})

    filter = TasksFilter(filter_data)

    # Delete all the tasks from the filter that are marked as complete
    filter.qs.filter(status="Complete").delete()

    context = get_table_data(request)

    return render(request, "agenda/tasks/table.html", context)


@login_required
def tasks_table(request):
    table_data = get_table_data(request)
    context = table_data
    return render(request, "agenda/tasks/table.html", context)
