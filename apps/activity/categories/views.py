"""Coding time/expense entries into a matter's activity categories.

Category management (add/edit/delete/reorder) lives on the matter detail
Categories tab (apps/matters/categories/views.py). Each entry belongs to at
most one category — accounting-style transaction coding — so assignment is
a plain dropdown, not a label-style apply modal, and no double-counting
guards are needed anywhere.
"""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.models import ActivityCategory
from apps.activity.time.models import TimeEntry

MATTER_ACTIVITY_TRIGGER = "matterActivityChanged"


@login_required
@require_POST
def set_category(request, object_type, object_id):
    """Set (or clear, with an empty category_id) an entry's category.

    Categorization is allowed on billing-locked entries — it never touches
    invoiced amounts.
    """
    if object_type == "time":
        obj = get_object_or_404(TimeEntry, id=object_id)
        field = "category"
    elif object_type == "expense":
        obj = get_object_or_404(ExpenseEntry, id=object_id)
        field = "activity_category"
    else:
        return HttpResponse("Invalid object type", status=400)

    category_id = request.POST.get("category_id", "")
    if category_id:
        # Scoped to the entry's matter so a foreign category can't be set.
        category = get_object_or_404(
            ActivityCategory, id=category_id, matter_id=obj.matter_id
        )
        setattr(obj, field, category)
    else:
        setattr(obj, field, None)
    obj.save()

    return HttpResponse(status=204, headers={"HX-Trigger": MATTER_ACTIVITY_TRIGGER})
