from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.activity.time.models import TimeEntry
from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding


@login_required
def activity_index(request, id):
    matter = get_object_or_404(Matter, pk=id)

    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    entries = TimeEntry.objects.filter(matter=id).order_by("-id")

    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key="activity_pagination"
    )

    context = {
        "app": "matters",
        "subapp": "activity",
        "matter": matter,
        "proceeding": proceeding,
        "entries": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "activity_pagination",
        "trigger_key": "matterActivityChanged",
    }

    return render(request, "matters/activity/main.html", context)


@login_required
def activity_list(request, id):
    matter = get_object_or_404(Matter, pk=id)

    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    entries = TimeEntry.objects.filter(matter=id).order_by("-id")

    pagination = CustomPaginator(
        entries, per_page=1, request=request, session_key="activity_pagination"
    )

    context = {
        "app": "matters",
        "subapp": "activity",
        "matter": matter,
        "proceeding": proceeding,
        "entries": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "activity_pagination",
        "trigger_key": "matterActivityChanged",
    }

    return render(request, "matters/activity/list.html", context)
