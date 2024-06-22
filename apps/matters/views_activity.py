from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.shortcuts import get_object_or_404

from apps.matters.models import Matter
from apps.matters.models import Proceeding
from apps.activity.models import TimeEntry


@login_required
def index(request, id):
    matter = get_object_or_404(Matter, pk=id)

    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    thirty_days = date.today() - timedelta(days=30)

    entries = TimeEntry.objects.filter(matter=id, date__gt=thirty_days).order_by("-id")

    context = {
        "page": "matters",
        "submodule": "activity",
        "matter": matter,
        "proceeding": proceeding,
        "entries": entries,
    }

    return render(request, "matters/activity/list.html", context)
