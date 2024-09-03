from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.activity.time.models import TimeEntry
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding


@login_required
def index(request, id):
    matter = get_object_or_404(Matter, pk=id)

    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    thirty_days = date.today() - timedelta(days=30)

    entries = TimeEntry.objects.filter(matter=id, date__gt=thirty_days).order_by("-id")

    context = {
        "app": "matters",
        "submodule": "activity",
        "matter": matter,
        "proceeding": proceeding,
        "entries": entries,
    }

    return render(request, "matters/activity/list.html", context)
