from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.activity.expenses.models import ExpenseEntry
from apps.activity.models import ActivityLabel
from apps.activity.time.models import TimeEntry
from apps.management.selection import (
    clear_selected_ids,
    get_selected_ids,
    get_session_key,
)
from apps.matters.models import Matter

from .forms import ActivityLabelForm

TIME_TRIGGER = "timeChanged"
EXPENSES_TRIGGER = "expensesChanged"


def _get_object_for_labels(object_type, object_id):
    """Helper to get object by type for label operations."""
    if object_type == "time":
        obj = get_object_or_404(TimeEntry, id=object_id)
        row_template = "activity/time/table-row.html"
        context_key = "entry"
    elif object_type == "expense":
        obj = get_object_or_404(ExpenseEntry, id=object_id)
        row_template = "activity/expenses/table-row.html"
        context_key = "expense"
    else:
        return None, None, None

    return obj, row_template, context_key


@login_required
def labels_index(request):
    """Main labels subtab view."""
    labels = ActivityLabel.objects.all()

    context = {
        "app": "activity",
        "subapp": "labels",
        "labels": labels,
    }

    return render(request, "activity/labels/main.html", context)


@login_required
def labels_list(request):
    """HTMX partial for labels list."""
    labels = ActivityLabel.objects.all()

    return render(request, "activity/labels/list.html", {"labels": labels})


@login_required
def add_label(request):
    """Add new activity label."""
    if request.method == "POST":
        form = ActivityLabelForm(request.POST, use_required_attribute=False)

        if form.is_valid():
            form.save()

            return HttpResponse(
                status=204, headers={"HX-Trigger": "activityLabelsChanged"}
            )

        return render(
            request,
            "activity/labels/form.html",
            {"form": form, "edit": False},
        )
    else:
        form = ActivityLabelForm(use_required_attribute=False)

        return render(
            request,
            "activity/labels/form.html",
            {"form": form, "edit": False},
        )


@login_required
def edit_label(request, label_id):
    """Edit existing activity label."""
    label = get_object_or_404(ActivityLabel, pk=label_id)

    if request.method == "POST":
        form = ActivityLabelForm(
            request.POST, instance=label, use_required_attribute=False
        )

        if form.is_valid():
            form.save()

            return HttpResponse(
                status=204, headers={"HX-Trigger": "activityLabelsChanged"}
            )
        return render(
            request,
            "activity/labels/form.html",
            {"form": form, "label": label, "edit": True},
        )
    else:
        form = ActivityLabelForm(instance=label, use_required_attribute=False)

        return render(
            request,
            "activity/labels/form.html",
            {"form": form, "label": label, "edit": True},
        )


@login_required
def delete_label(request, label_id):
    """Delete activity label."""

    label = get_object_or_404(ActivityLabel, pk=label_id)
    label.delete()

    return HttpResponse(status=204, headers={"HX-Trigger": "activityLabelsChanged"})


@login_required
def labels_apply_modal(request, object_type, object_id):
    """Open modal to apply labels to an object."""
    obj, _, _ = _get_object_for_labels(object_type, object_id)
    if obj is None:
        return HttpResponse("Invalid object type", status=400)

    view = request.GET.get("view", "")
    matter_id = request.GET.get("matter_id", "")

    return render(
        request,
        "activity/labels/apply-modal.html",
        {
            "object": obj,
            "object_type": object_type,
            "view": view,
            "matter_id": matter_id,
        },
    )


@login_required
def labels_search(request, object_type, object_id):
    """Search labels for apply modal."""
    obj, _, _ = _get_object_for_labels(object_type, object_id)

    if obj is None:
        return HttpResponse("Invalid object type", status=400)

    query = request.GET.get("q", "").strip()
    view = request.GET.get("view", "")
    matter_id = request.GET.get("matter_id", "")

    labels = ActivityLabel.objects.all()

    if query:
        labels = labels.filter(name__icontains=query)

    # Exclude already-applied labels
    existing_label_ids = obj.labels.values_list("id", flat=True)
    labels = labels.exclude(id__in=existing_label_ids)

    return render(
        request,
        "activity/labels/apply-results.html",
        {
            "labels": labels,
            "object": obj,
            "object_type": object_type,
            "view": view,
            "matter_id": matter_id,
        },
    )


@login_required
def add_label_to(request, object_type, object_id):
    """Add a label to a time/expense entry."""
    obj, row_template, context_key = _get_object_for_labels(object_type, object_id)

    if obj is None:
        return HttpResponse("Invalid object type", status=400)

    label_id = request.POST.get("label_id")
    if label_id:
        try:
            label = ActivityLabel.objects.get(id=label_id)
            obj.labels.add(label)
        except ActivityLabel.DoesNotExist:
            pass

    # Check if this is from matter activity view
    view = request.POST.get("view", "")
    matter_id = request.POST.get("matter_id", "")

    if view == "matter" and matter_id:
        matter = get_object_or_404(Matter, pk=matter_id)
        context = {
            context_key: obj,
            "matter": matter,
            "selected_entries": request.session.get(
                f"selected_matter_activity_{matter_id}", []
            ),
        }
        return render(request, "matters/activity/table-row.html", context)

    context = {
        context_key: obj,
        "show_select": True,
    }

    if object_type == "time":
        context["selected_time"] = request.session.get("selected_time_entries", [])
    else:
        context["selected_expenses"] = request.session.get("selected_expenses", [])

    return render(request, row_template, context)


@login_required
def remove_label_from(request, object_type, object_id):
    """Remove a label from a time/expense entry."""
    obj, row_template, context_key = _get_object_for_labels(object_type, object_id)

    if obj is None:
        return HttpResponse("Invalid object type", status=400)

    label_id = request.POST.get("label_id")
    if label_id:
        try:
            label = ActivityLabel.objects.get(id=label_id)
            obj.labels.remove(label)
        except ActivityLabel.DoesNotExist:
            pass

    # Check if this is from matter activity view
    view = request.POST.get("view", "")
    matter_id = request.POST.get("matter_id", "")

    if view == "matter" and matter_id:
        matter = get_object_or_404(Matter, pk=matter_id)
        context = {
            context_key: obj,
            "matter": matter,
            "selected_entries": request.session.get(
                f"selected_matter_activity_{matter_id}", []
            ),
        }
        return render(request, "matters/activity/table-row.html", context)

    context = {
        context_key: obj,
        "show_select": True,
    }

    if object_type == "time":
        context["selected_time"] = request.session.get("selected_time_entries", [])
    else:
        context["selected_expenses"] = request.session.get("selected_expenses", [])

    return render(request, row_template, context)


@login_required
def labels_create_and_apply(request, object_type, object_id):
    """Create a new label and apply it to an entry."""
    obj, row_template, context_key = _get_object_for_labels(object_type, object_id)

    if obj is None:
        return HttpResponse("Invalid object type", status=400)

    name = request.POST.get("name", "").strip()
    color = request.POST.get("color", "gray")

    if name:
        # Check if label with this name already exists
        label, created = ActivityLabel.objects.get_or_create(
            name=name,
            defaults={"color": color},
        )
        obj.labels.add(label)

    # Check if this is from matter activity view
    view = request.POST.get("view", "")
    matter_id = request.POST.get("matter_id", "")

    if view == "matter" and matter_id:
        matter = get_object_or_404(Matter, pk=matter_id)
        context = {
            context_key: obj,
            "matter": matter,
            "selected_entries": request.session.get(
                f"selected_matter_activity_{matter_id}", []
            ),
        }
        return render(request, "matters/activity/table-row.html", context)

    context = {
        context_key: obj,
        "show_select": True,
    }

    if object_type == "time":
        context["selected_time"] = request.session.get("selected_time_entries", [])
    else:
        context["selected_expenses"] = request.session.get("selected_expenses", [])

    return render(request, row_template, context)


@login_required
def bulk_apply_label_time(request):
    """Bulk apply labels to selected time entries."""
    key = get_session_key("selected_time")
    selected_ids = get_selected_ids(request, key)

    if not selected_ids:
        return HttpResponse(status=400, content="No time entries selected.")

    if request.method == "POST":
        label_ids = request.POST.getlist("labels")
        action = request.POST.get("action", "add")

        if label_ids:
            entries = TimeEntry.objects.filter(id__in=selected_ids)
            labels = ActivityLabel.objects.filter(id__in=label_ids)

            for entry in entries:
                if action == "add":
                    entry.labels.add(*labels)
                elif action == "remove":
                    entry.labels.remove(*labels)
                elif action == "set":
                    entry.labels.set(labels)

            clear_selected_ids(request, key)
            return HttpResponse(status=204, headers={"HX-Trigger": TIME_TRIGGER})

    labels = ActivityLabel.objects.all()
    context = {
        "selected_count": len(selected_ids),
        "labels": labels,
        "entry_type": "time",
    }

    return render(request, "activity/labels/bulk-apply-form.html", context)


@login_required
def bulk_apply_label_expenses(request):
    """Bulk apply labels to selected expense entries."""
    key = get_session_key("selected_expenses")
    selected_ids = get_selected_ids(request, key)

    if not selected_ids:
        return HttpResponse(status=400, content="No expense entries selected.")

    if request.method == "POST":
        label_ids = request.POST.getlist("labels")
        action = request.POST.get("action", "add")

        if label_ids:
            entries = ExpenseEntry.objects.filter(id__in=selected_ids)
            labels = ActivityLabel.objects.filter(id__in=label_ids)

            for entry in entries:
                if action == "add":
                    entry.labels.add(*labels)
                elif action == "remove":
                    entry.labels.remove(*labels)
                elif action == "set":
                    entry.labels.set(labels)

            clear_selected_ids(request, key)
            return HttpResponse(status=204, headers={"HX-Trigger": EXPENSES_TRIGGER})

    labels = ActivityLabel.objects.all()
    context = {
        "selected_count": len(selected_ids),
        "labels": labels,
        "entry_type": "expenses",
    }

    return render(request, "activity/labels/bulk-apply-form.html", context)
