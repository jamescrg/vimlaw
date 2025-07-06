from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


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
