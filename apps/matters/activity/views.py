import os
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.activity.time.models import TimeEntry
from apps.management.pagination import CustomPaginator
from apps.matters.generate_activity_report import generate_activity_report
from apps.matters.models import Matter


@login_required
def activity_index(request, id):
    matter = get_object_or_404(Matter, pk=id)

    entries = TimeEntry.objects.filter(matter=id).order_by("-id")

    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key="activity_pagination"
    )

    context = {
        "app": "matters",
        "subapp": "activity",
        "matter": matter,
        "entries": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "activity_pagination",
        "trigger_key": "matterActivityChanged",
    }

    return render(request, "matters/activity/main.html", context)


@login_required
def activity_list(request, id):
    matter = get_object_or_404(Matter, pk=id)

    entries = TimeEntry.objects.filter(matter=id).order_by("-id")

    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key="activity_pagination"
    )

    context = {
        "app": "matters",
        "subapp": "activity",
        "matter": matter,
        "entries": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "activity_pagination",
        "trigger_key": "matterActivityChanged",
    }

    return render(request, "matters/activity/list.html", context)


@login_required
def activity_report(request, id):
    matter = get_object_or_404(Matter, pk=id)
    file = generate_activity_report(matter, request)

    current_date = datetime.now().strftime("%Y-%m-%d")

    with open(file.name, "rb") as pdf:
        response = HttpResponse(pdf.read(), content_type="application/pdf")
        filename = f'filename="Activity Report - {matter.name} - {current_date}.pdf"'
        response["Content-Disposition"] = f"attachment; {filename}"

    os.unlink(file.name)

    return response
