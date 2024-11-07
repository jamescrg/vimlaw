from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render

from apps.matters.models import Matter


@login_required
def collection_index(request):
    matters = Matter.objects.filter(status__in=["Open", "Complete"])

    # Convert queryset to list so it's sortable by custom properties
    matter_list = list(matters)
    matter_list.sort(key=lambda x: x.value["invoices"]["due"], reverse=True)

    page = request.GET.get("page")
    pagination = Paginator(matter_list, 10).get_page(page)

    total_due = 0
    for matter in matters:
        total_due += matter.value["invoices"]["due"]

    context = {
        "app": "billing",
        "subapp": "collection",
        "matters": pagination.object_list,
        "pagination": pagination,
        "total_due": total_due,
    }

    return render(request, "billing/collection/list.html", context)
