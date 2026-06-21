from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render

from apps.management.filter_manager import FilterManager

from .aggregation import build_activity_context
from .filters import ActivityReportFilter


@login_required
@staff_member_required
def activity_index(request):
    return render(
        request, "reports/activity/main.html", build_activity_context(request)
    )


@login_required
@staff_member_required
def activity_list(request):
    return render(
        request, "reports/activity/list.html", build_activity_context(request)
    )


@login_required
@staff_member_required
def activity_filter(request):
    filter_manager = FilterManager(request, ActivityReportFilter, "activity_filter")

    if filter_manager.process_filter():
        return HttpResponse(status=204, headers={"HX-Trigger": "activityChanged"})

    # Get current filter data from session for display
    filter_data = request.session.get("activity_filter", {})

    return render(request, "reports/activity/filter.html", {"filter_data": filter_data})
