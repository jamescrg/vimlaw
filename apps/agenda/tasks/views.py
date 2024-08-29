from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import Http404
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

    table_data = get_table_data(request)

    # save the currently selected matter in the add task form
    # so multiple tasks can quickly be added to a matter
    tasks_matter = request.session.get("tasks_matter")

    context = {
        "page": "agenda",
        "subpage": "tasks",
        "show_events": show_events,
        "tasks_matter": tasks_matter,
    }

    context = context | table_data
    return render(request, "agenda/tasks/list.html", context)


@login_required
def tasks_select(request):
    request.session["show_events"] = False
    request.session["hide_expire"] = date.today().strftime("%s")
    return redirect("/agenda")


@login_required
def tasks_add(request):
    task = Task()

    task.user_id = request.user.id

    matter = get_object_or_404(Matter, pk=request.POST.get("matter"))
    task.matter = matter

    task.status = "Pending"

    task.description = request.POST.get("description")
    if task.description[:2] == "! ":
        task.description = task.description[2:]
        task.priority = 1
    elif task.description[:1] == "!":
        task.description = task.description[1:]
        task.priority = 1

    task.date_due = date.today()
    task.save()

    request.session["agenda_matter"] = matter.id

    return redirect("/agenda")


@login_required
def tasks_edit(request, id):
    if request.method == "POST":
        try:
            task = Task.objects.filter(pk=id).get()
        except (Task.DoesNotExist, ValueError):
            raise Http404("Record not found.")

        form = TaskForm(request.POST, instance=task)
        if form.is_valid():
            task = form.save(commit=False)
            task.save()

        return redirect("/agenda")

    else:
        task = get_object_or_404(Task, pk=id)

        # pull the list of matters
        matter_list = Matter.objects.filter(status="Open").order_by("name")
        user_list = CustomUser.objects.all().order_by("username")

        # make sure the matter associated with the event is in the list
        # if not, add it
        # this ensures the matter is available in the form select element
        # even when the matter is closed
        if task.matter and task.matter not in matter_list:
            matter_list |= Matter.objects.filter(pk=task.matter.id)

        form = TaskForm(instance=task)
        form.fields["matter"].queryset = matter_list
        form.fields["user"].queryset = user_list

        context = {
            "page": "agenda",
            "edit": True,
            "task": task,
            "action": f"/agenda/tasks/{id}/edit",
            "form": form,
        }

        return render(request, "agenda/tasks/form-edit.html", context)


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
def tasks_filter_user(request, user):
    filter_data = request.session.get("tasks_filter", {})

    if user == "All":
        filter_data["user"] = None
    else:
        user_id = CustomUser.objects.get(username=user).id

        filter_data["user"] = user_id
        filter_data["status"] = "Pending"

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
    users = CustomUser.objects.all()

    task.user = user
    task.save()

    context = {
        "task": task,
        "user": user,
        "users": users,
    }
    return render(request, "agenda/tasks/change-user.html", context)
