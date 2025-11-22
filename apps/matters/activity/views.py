import os
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.activity.time.models import TimeEntry
from apps.activity.time.summary import calculate_summary
from apps.management.pagination import CustomPaginator
from apps.matters.generate_activity_report import generate_activity_report
from apps.matters.models import Matter


@login_required
def activity_index(request, id):
    matter = get_object_or_404(Matter, pk=id)

    # Get sort order from session, default to newest-first
    sort_order = request.session.get("matter_activity_sort", "-id")
    entries = TimeEntry.objects.filter(matter=id).order_by(sort_order)

    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key="activity_pagination"
    )

    # Calculate summary for all entries (not just paginated)
    summary = calculate_summary(entries)

    context = {
        "app": "matters",
        "subapp": "activity",
        "matter": matter,
        "entries": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "activity_pagination",
        "trigger_key": "matterActivityChanged",
        "summary": summary,
    }

    return render(request, "matters/activity/main.html", context)


@login_required
def activity_list(request, id):
    matter = get_object_or_404(Matter, pk=id)

    # Get sort order from session, default to newest-first
    sort_order = request.session.get("matter_activity_sort", "-id")
    entries = TimeEntry.objects.filter(matter=id).order_by(sort_order)

    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key="activity_pagination"
    )

    # Calculate summary for all entries (not just paginated)
    summary = calculate_summary(entries)

    context = {
        "app": "matters",
        "subapp": "activity",
        "matter": matter,
        "entries": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "activity_pagination",
        "trigger_key": "matterActivityChanged",
        "summary": summary,
    }

    return render(request, "matters/activity/list.html", context)


@login_required
def activity_sort(request, id):
    """Toggle sorting between newest-first and oldest-first."""
    matter = get_object_or_404(Matter, pk=id)

    # Get current sort order from session, default to newest-first (-id)
    current_order = request.session.get("matter_activity_sort", "-id")

    # Toggle between -id (newest) and id (oldest)
    new_order = "id" if current_order == "-id" else "-id"
    request.session["matter_activity_sort"] = new_order

    entries = TimeEntry.objects.filter(matter=id).order_by(new_order)

    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key="activity_pagination"
    )

    # Calculate summary for all entries (not just paginated)
    summary = calculate_summary(entries)

    context = {
        "app": "matters",
        "subapp": "activity",
        "matter": matter,
        "entries": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "activity_pagination",
        "trigger_key": "matterActivityChanged",
        "summary": summary,
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
