"""Managing a matter's activity categories — the Categories sub-view of
the Activity tab: a sortable table (drag to set the Fee Claim Report
section order) with the case-style add/edit modal."""

import json

from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.accounts.access import matter_access_required
from apps.activity.categories.forms import ActivityCategoriesForm
from apps.activity.models import ActivityCategory
from apps.matters.models import Matter

TRIGGER = "matterActivityChanged"


@login_required
@matter_access_required
def add_category(request, id):
    matter = get_object_or_404(Matter, pk=id)

    if request.method == "POST":
        form = ActivityCategoriesForm(
            request.POST,
            instance=ActivityCategory(matter=matter),
            use_required_attribute=False,
        )

        if form.is_valid():
            category = form.save(commit=False)
            # New categories join the end of the sequence.
            max_position = ActivityCategory.objects.filter(matter=matter).aggregate(
                Max("position")
            )["position__max"]
            category.position = 0 if max_position is None else max_position + 1
            category.save()

            return HttpResponse(status=204, headers={"HX-Trigger": TRIGGER})

        return render(
            request,
            "matters/categories/form.html",
            {"form": form, "edit": False, "matter": matter},
        )
    else:
        form = ActivityCategoriesForm(use_required_attribute=False)

        return render(
            request,
            "matters/categories/form.html",
            {"form": form, "edit": False, "matter": matter},
        )


@login_required
def edit_category(request, category_id):
    category = get_object_or_404(ActivityCategory, pk=category_id)

    if request.method == "POST":
        form = ActivityCategoriesForm(
            request.POST, instance=category, use_required_attribute=False
        )

        if form.is_valid():
            form.save()

            return HttpResponse(status=204, headers={"HX-Trigger": TRIGGER})

        return render(
            request,
            "matters/categories/form.html",
            {
                "form": form,
                "category": category,
                "edit": True,
                "matter": category.matter,
            },
        )
    else:
        form = ActivityCategoriesForm(instance=category, use_required_attribute=False)

        return render(
            request,
            "matters/categories/form.html",
            {
                "form": form,
                "category": category,
                "edit": True,
                "matter": category.matter,
            },
        )


@login_required
def delete_category(request, category_id):
    category = get_object_or_404(ActivityCategory, pk=category_id)
    category.delete()

    return HttpResponse(status=204, headers={"HX-Trigger": TRIGGER})


@login_required
@matter_access_required
@require_POST
def categories_reorder(request, id):
    """Persist a drag-and-drop reordering of the matter's categories."""
    matter = get_object_or_404(Matter, pk=id)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    category_ids = data.get("category_ids", [])
    if not category_ids:
        return JsonResponse(
            {"success": False, "error": "No category IDs provided"}, status=400
        )

    for index, category_id in enumerate(category_ids):
        ActivityCategory.objects.filter(id=category_id, matter=matter).update(
            position=index
        )

    return JsonResponse({"success": True})


@login_required
@require_POST
def toggle_claimed(request, category_id):
    """Flip a category's claimed flag from the categories table. Always safe:
    entries live in exactly one category, so no double-counting can result."""
    category = get_object_or_404(ActivityCategory, pk=category_id)
    category.claimed = not category.claimed
    category.save()

    return HttpResponse(status=204, headers={"HX-Trigger": TRIGGER})
