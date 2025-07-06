from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render

from apps.management.filter_manager import FilterManager

from .filters import ReportsDateFilter


@login_required
@staff_member_required
def reports_index(request):
    request.session["reports-view"] = "list"
    return redirect("/reports/revenue/")


@login_required
@staff_member_required
def reports_list(request):
    request.session["reports-view"] = "list"
    return redirect("/reports/revenue/")


@login_required
@staff_member_required
def reports_filter(request):
    filter_manager = FilterManager(request, ReportsDateFilter, "reports_filter")

    if filter_manager.process_filter():
        return HttpResponse(status=204, headers={"HX-Trigger": "reportsChanged"})

    # Get current filter data from session for display
    filter_data = request.session.get("reports_filter", {})

    return render(request, "reports/filter.html", {"filter_data": filter_data})
