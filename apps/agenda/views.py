from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from django.shortcuts import redirect
from django.shortcuts import get_object_or_404

from apps.matters.models import Matter
from apps.agenda.models import Task
from apps.agenda.forms import TaskForm
from apps.events.models import Event
from apps.accounts.models import CustomUser
from apps.agenda.tasks import get_table_data
from apps.agenda.filter import Filter


@login_required
def index(request):
    page = "agenda"

    # check whether events have been hidden
    show_events = request.session.get("show_events", True)

    # if events are hidden, check the date they were hidden
    # if that date is less than today, show them
    if not show_events:
        today = date.today()
        timestamp = int(request.session.get("hide_expire"))
        old_date = date.fromtimestamp(timestamp)
        if today > old_date:
            show_events = True
            request.session["show_events"] = True

    # if events are shown, load them
    if show_events:
        today = date.today()
        three_weeks_out = today + timedelta(days=21)
        three_days_out = today + timedelta(days=3)
        events = Event.objects.filter(
            status="Pending", date__lt=three_weeks_out
        ).order_by("date")
    else:
        events = None
        three_days_out = None

    table_data = get_table_data(request)

    # save the currently selected matter in the add task form
    # so multiple tasks can quickly be added to a matter
    agenda_matter = request.session.get("agenda_matter")

    context = {
        "page": page,
        "show_events": show_events,
        "events": events,
        "three_days_out": three_days_out,
        "agenda_matter": agenda_matter,
    }

    context = context | table_data
    return render(request, "agenda/content.html", context)


@login_required
def toggle_events(request):
    show_events = request.session.get("show_events", True)
    if show_events:
        request.session["show_events"] = False
        request.session["hide_expire"] = date.today().strftime("%s")
    else:
        request.session["show_events"] = True
    return redirect("/agenda/")


@login_required
def add(request):
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

    return redirect("agenda")


@login_required
def edit(request, id):
    user_id = request.user.id

    if request.method == "POST":
        try:
            task = Task.objects.filter(pk=id).get()
        except:
            raise Http404("Record not found.")

        form = TaskForm(request.POST, instance=task)
        if form.is_valid():
            task = form.save(commit=False)
            task.save()

        return redirect("agenda")

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
            "action": f"/agenda/{id}/edit",
            "form": form,
        }

        return render(request, "agenda/task-form-edit.html", context)


@login_required
def delete(request, id):
    entry = get_object_or_404(Task, pk=id)
    entry.delete()
    return redirect("/agenda")


@login_required
def filter(request):
    filter = Filter(request).values
    if filter["matter"]:
        filter["matter"] = int(filter["matter"])
    matters = Matter.objects.filter(status="Open").order_by("name")
    users = CustomUser.objects.all().order_by("username")
    context = {
        "page": "agenda",
        "filter": filter,
        "matters": matters,
        "users": users,
    }
    return render(request, "agenda/filter.html", context)


@login_required
def filter_update(request):
    filter = Filter(request)
    filter.update(request)
    return redirect("/agenda")


@login_required
def filter_quick(request, quick_filter):
    filter = Filter(request)
    filter.set_quick_filter(request, quick_filter)
    context = get_table_data(request)
    return render(request, "agenda/tasks-table.html", context)


@login_required
def filter_sort(request, new_field):
    filter = Filter(request)
    filter.sort(request, new_field)
    context = get_table_data(request)
    return render(request, "agenda/tasks-table.html", context)


@login_required
def task_status(request, id):
    task = get_object_or_404(Task, pk=id)
    if task.status == "Complete":
        task.status = "Pending"
    else:
        task.status = "Complete"
    task.save()
    context = {
        "task": task,
    }
    return render(request, "agenda/task-status.html", context)
