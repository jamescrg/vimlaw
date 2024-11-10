from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.management.pagination import CustomPaginator
from apps.matters.models import Matter


@login_required
def collection_index(request):
    context = {
        "app": "billing",
        "subapp": "collection",
    }

    return render(request, "billing/collection/main.html", context)


@login_required
def collection_list(request):
    matters = Matter.objects.filter(status__in=["Open", "Complete"])

    # Convert queryset to list so it's sortable by custom properties
    matter_list = list(matters)
    matter_list.sort(key=lambda x: x.value["invoices"]["due"], reverse=True)

    pagination = CustomPaginator(
        matter_list, per_page=10, request=request, session_key="collection_pagination"
    )

    total_due = 0
    for matter in matters:
        total_due += matter.value["invoices"]["due"]

    context = {
        "app": "billing",
        "subapp": "collection",
        "matters": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "collection_pagination",
        "trigger_key": "collectionChanged",
        "total_due": total_due,
    }

    return render(request, "billing/collection/list.html", context)
