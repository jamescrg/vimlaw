from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.agenda.unbilled.unbilled import get_unbilled_data


@login_required
@staff_member_required
def unbilled_index(request):
    """Unbilled view - Admin only."""
    context = get_unbilled_data(request)

    context = context | {
        "app": "agenda",
        "subapp": "unbilled",
    }

    return render(request, "agenda/unbilled/main.html", context)


@login_required
@staff_member_required
def unbilled_list(request):
    """Unbilled list view for HTMX - Admin only."""
    context = get_unbilled_data(request)

    return render(request, "agenda/unbilled/list.html", context)


@login_required
@staff_member_required
def unbilled_sort(request, order):
    """Handle sorting for unbilled list - Admin only."""
    filter_data = request.session.get("unbilled_filter", {})

    current_order = filter_data.get("order_by", "")

    # Toggle sort direction if clicking the same column
    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["unbilled_filter"] = filter_data
    request.session.modified = True

    return redirect("agenda:unbilled-list")
