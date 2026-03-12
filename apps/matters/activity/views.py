import os
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.activity.models import ActivityLabel
from apps.activity.time.models import TimeEntry
from apps.activity.time.summary import calculate_summary
from apps.management.pagination import CustomPaginator
from apps.management.selection import (
    all_visible_selected,
    clear_selected_ids,
    get_selected_ids,
    get_session_key,
    select_all_ids,
    selection_response,
    toggle_id,
)
from apps.matters.generate_activity_report import generate_activity_report
from apps.matters.models import Matter


@login_required
def activity_index(request, id):
    matter = get_object_or_404(Matter, pk=id)

    # Get sort order from session, default to newest-first
    sort_order = request.session.get("matter_activity_sort", "-id")
    entries = TimeEntry.objects.filter(matter=id).order_by(sort_order)

    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key="activity_pagination"
    )

    # Calculate summary for all entries (not just paginated)
    summary = calculate_summary(entries)

    # Get selection data
    session_key = get_session_key("selected_matter_activity", id)
    selected_entries = get_selected_ids(request, session_key)

    visible_ids = [entry.id for entry in pagination.get_object_list()]
    all_selected = all_visible_selected(selected_entries, visible_ids)

    context = {
        "app": "matters",
        "subapp": "activity",
        "matter": matter,
        "entries": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "activity_pagination",
        "trigger_key": "matterActivityChanged",
        "summary": summary,
        "selected_entries": selected_entries,
        "all_selected": all_selected,
    }

    return render(request, "matters/activity/main.html", context)


@login_required
def activity_list(request, id):
    matter = get_object_or_404(Matter, pk=id)

    # Get sort order from session, default to newest-first
    sort_order = request.session.get("matter_activity_sort", "-id")
    entries = TimeEntry.objects.filter(matter=id).order_by(sort_order)

    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key="activity_pagination"
    )

    # Calculate summary for all entries (not just paginated)
    summary = calculate_summary(entries)

    # Get selection data
    session_key = get_session_key("selected_matter_activity", id)
    selected_entries = get_selected_ids(request, session_key)

    visible_ids = [entry.id for entry in pagination.get_object_list()]
    all_selected = all_visible_selected(selected_entries, visible_ids)

    context = {
        "app": "matters",
        "subapp": "activity",
        "matter": matter,
        "entries": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "activity_pagination",
        "trigger_key": "matterActivityChanged",
        "summary": summary,
        "selected_entries": selected_entries,
        "all_selected": all_selected,
    }

    return render(request, "matters/activity/list.html", context)


@login_required
def activity_sort(request, id):
    """Toggle sorting between newest-first and oldest-first."""
    matter = get_object_or_404(Matter, pk=id)

    # Get current sort order from session, default to newest-first (-id)
    current_order = request.session.get("matter_activity_sort", "-id")

    # Toggle between -id (newest) and id (oldest)
    new_order = "id" if current_order == "-id" else "-id"
    request.session["matter_activity_sort"] = new_order

    entries = TimeEntry.objects.filter(matter=id).order_by(new_order)

    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key="activity_pagination"
    )

    # Calculate summary for all entries (not just paginated)
    summary = calculate_summary(entries)

    # Get selection data
    session_key = get_session_key("selected_matter_activity", id)
    selected_entries = get_selected_ids(request, session_key)

    visible_ids = [entry.id for entry in pagination.get_object_list()]
    all_selected = all_visible_selected(selected_entries, visible_ids)

    context = {
        "app": "matters",
        "subapp": "activity",
        "matter": matter,
        "entries": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "activity_pagination",
        "trigger_key": "matterActivityChanged",
        "summary": summary,
        "selected_entries": selected_entries,
        "all_selected": all_selected,
    }

    return render(request, "matters/activity/list.html", context)


@login_required
def activity_report(request, id):
    matter = get_object_or_404(Matter, pk=id)
    file = generate_activity_report(matter, request)

    current_date = datetime.now().strftime("%Y-%m-%d")

    with open(file.name, "rb") as pdf:
        response = HttpResponse(pdf.read(), content_type="application/pdf")
        filename = f'filename="Activity Report - {matter.name} - {current_date}.pdf"'
        response["Content-Disposition"] = f"attachment; {filename}"

    os.unlink(file.name)

    return response


MATTER_ACTIVITY_TRIGGER = "matterActivityChanged"


@login_required
@require_POST
def activity_toggle_select(request, matter_id, entry_id):
    get_object_or_404(TimeEntry, pk=entry_id)
    toggle_id(request, get_session_key("selected_matter_activity", matter_id), entry_id)

    return selection_response(MATTER_ACTIVITY_TRIGGER)


@login_required
@require_POST
def activity_select_all(request, matter_id):
    sort_order = request.session.get("matter_activity_sort", "-id")
    entries = TimeEntry.objects.filter(matter=matter_id).order_by(sort_order)

    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key="activity_pagination"
    )

    visible_ids = [entry.id for entry in pagination.get_object_list()]
    select_all_ids(
        request, get_session_key("selected_matter_activity", matter_id), visible_ids
    )

    return selection_response(MATTER_ACTIVITY_TRIGGER)


@login_required
@require_POST
def activity_clear_selection(request, matter_id):
    clear_selected_ids(request, get_session_key("selected_matter_activity", matter_id))

    return selection_response(MATTER_ACTIVITY_TRIGGER)


@login_required
def activity_bulk_update_matter(request, matter_id):
    key = get_session_key("selected_matter_activity", matter_id)
    selected_entries = get_selected_ids(request, key)

    if not selected_entries:
        return HttpResponse(status=400, content="No time entries selected.")

    if request.method == "POST":
        new_matter_id = request.POST.get("matter")
        if new_matter_id:
            new_matter = get_object_or_404(Matter, pk=new_matter_id)
            entries = TimeEntry.objects.filter(id__in=selected_entries)

            for entry in entries:
                # Clear invoice if matter changes
                entry.matter = new_matter
                entry.invoice = None

                entry.save()

            clear_selected_ids(request, key)
            return HttpResponse(
                status=204, headers={"HX-Trigger": MATTER_ACTIVITY_TRIGGER}
            )

    matters = Matter.objects.filter(
        status__in=["Pending", "Open", "Complete"]
    ).order_by("name")

    context = {
        "selected_count": len(selected_entries),
        "matters": matters,
        "entry_type": "time",
        "matter_id": matter_id,
    }

    return render(request, "matters/activity/bulk-matter-form.html", context)


@login_required
def activity_bulk_update_comp(request, matter_id):
    key = get_session_key("selected_matter_activity", matter_id)
    selected_entries = get_selected_ids(request, key)

    if not selected_entries:
        return HttpResponse(status=400, content="No time entries selected.")

    if request.method == "POST":
        comp_value = request.POST.get("comp")

        if comp_value in ["true", "false"]:
            entries = TimeEntry.objects.filter(id__in=selected_entries)
            comp_bool = comp_value == "true"

            for entry in entries:
                entry.comp = comp_bool
                entry.save()

            clear_selected_ids(request, key)
            return HttpResponse(
                status=204, headers={"HX-Trigger": MATTER_ACTIVITY_TRIGGER}
            )

    context = {
        "selected_count": len(selected_entries),
        "entry_type": "time",
        "matter_id": matter_id,
    }

    return render(request, "matters/activity/bulk-comp-form.html", context)


@login_required
def activity_bulk_apply_labels(request, matter_id):
    key = get_session_key("selected_matter_activity", matter_id)
    selected_entries = get_selected_ids(request, key)

    if not selected_entries:
        return HttpResponse(status=400, content="No time entries selected.")

    if request.method == "POST":
        label_ids = request.POST.getlist("labels")
        action = request.POST.get("action", "add")

        if label_ids:
            entries = TimeEntry.objects.filter(id__in=selected_entries)
            labels = ActivityLabel.objects.filter(id__in=label_ids)

            for entry in entries:
                if action == "add":
                    entry.labels.add(*labels)
                elif action == "remove":
                    entry.labels.remove(*labels)
                elif action == "set":
                    entry.labels.set(labels)

            clear_selected_ids(request, key)
            return HttpResponse(
                status=204, headers={"HX-Trigger": MATTER_ACTIVITY_TRIGGER}
            )

    labels = ActivityLabel.objects.all()

    context = {
        "selected_count": len(selected_entries),
        "labels": labels,
        "matter_id": matter_id,
    }

    return render(request, "matters/activity/bulk-labels-form.html", context)
