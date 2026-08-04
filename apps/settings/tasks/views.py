from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.settings.models import Firm
from apps.settings.tasks.forms import TasksSettingsForm
from utils.toasts import toast_success


@login_required
def tasks_index(request):
    """Tasks settings page: firm-wide task entry behaviour."""
    firm = Firm.objects.first()

    if request.method == "POST":
        form = TasksSettingsForm(request.POST, instance=firm)
        saved = form.is_valid()
        if saved:
            firm = form.save()
            form = TasksSettingsForm(instance=firm)
        response = render(request, "settings/tasks/form.html", {"form": form})
        if saved:
            toast_success(response, "Task settings updated")
        return response

    return render(
        request,
        "settings/tasks/index.html",
        {
            "subapp": "tasks",
            "form": TasksSettingsForm(instance=firm),
        },
    )
