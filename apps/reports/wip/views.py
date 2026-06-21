from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .aggregation import build_wip_context


@login_required
@staff_member_required
def wip_index(request):
    return render(request, "reports/wip/main.html", build_wip_context(request))


@login_required
@staff_member_required
def wip_list(request):
    return render(request, "reports/wip/list.html", build_wip_context(request))
