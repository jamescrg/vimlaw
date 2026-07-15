import os
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.accounts.access import matter_access_required
from apps.activity.expenses.models import ExpenseEntry
from apps.activity.expenses.summary import (
    calculate_summary as calculate_expense_summary,
)
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


def get_matter_activity_data(request, matter):
    """Context for the matter activity subtab, honoring the Time/Expenses toggle
    (session `matter_activity_view`, default 'time'). Expenses is a simple
    read-only list; Time keeps the existing sort/paginate/select machinery."""
    view = request.session.get("matter_activity_view", "time")

    if view == "expenses":
        expense_entries = list(
            ExpenseEntry.objects.filter(matter=matter)
            .select_related("user", "matter")
            .order_by("-date", "-id")
        )
        return {
            "matter": matter,
            "activity_view": "expenses",
            "expense_entries": expense_entries,
            "expense_summary": calculate_expense_summary(expense_entries),
        }

    sort_order = request.session.get("matter_activity_sort", "-id")
    entries = TimeEntry.objects.filter(matter=matter).order_by(sort_order)
    pagination = CustomPaginator(
        entries, per_page=10, request=request, session_key="activity_pagination"
    )
    selected_entries = get_selected_ids(
        request, get_session_key("selected_matter_activity", matter.id)
    )
    visible_ids = [e.id for e in pagination.get_object_list()]
    return {
        "matter": matter,
        "activity_view": "time",
        "entries": pagination.get_object_list(),
        "pagination": pagination,
        "session_key": "activity_pagination",
        "trigger_key": "matterActivityChanged",
        "summary": calculate_summary(entries),
        "selected_entries": selected_entries,
        "all_selected": all_visible_selected(selected_entries, visible_ids),
        "matters": Matter.objects.filter(
            status__in=["Pending", "Open", "Complete"]
        ).order_by("name"),
    }


@login_required
@matter_access_required
@require_POST
def activity_view(request, id, view):
    """Switch the subtab between the time and expenses lists. The #rates panel
    reloads via the matterActivityChanged trigger."""
    get_object_or_404(Matter, pk=id)
    request.session["matter_activity_view"] = (
        "expenses" if view == "expenses" else "time"
    )
    return selection_response("matterActivityChanged")


@login_required
@matter_access_required
def activity_index(request, id):
    matter = get_object_or_404(Matter, pk=id)
    context = {
        "app": "matters",
        "subapp": "activity",
        "tab_template": "matters/activity/list.html",
        **get_matter_activity_data(request, matter),
    }
    return render(request, "matters/includes/tab-page.html", context)


@login_required
@matter_access_required
def activity_list(request, id):
    matter = get_object_or_404(Matter, pk=id)
    context = {
        "app": "matters",
        "subapp": "activity",
        **get_matter_activity_data(request, matter),
    }
    return render(request, "matters/activity/list.html", context)


@login_required
@matter_access_required
def activity_sort(request, id):
    """Toggle sorting between newest-first and oldest-first."""
    get_object_or_404(Matter, pk=id)

    current_order = request.session.get("matter_activity_sort", "-id")
    request.session["matter_activity_sort"] = "id" if current_order == "-id" else "-id"

    # Same pattern as the other toolbar actions: a 204 + trigger, so the
    # #matterActivity wrapper re-fetches the whole tab (toolbar + table).
    # Rendering list.html into #matterActivityTable nested a duplicate toolbar.
    return selection_response(MATTER_ACTIVITY_TRIGGER)


@login_required
@matter_access_required
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
@matter_access_required
@require_POST
def activity_toggle_select(request, matter_id, entry_id):
    get_object_or_404(TimeEntry, pk=entry_id)
    toggle_id(request, get_session_key("selected_matter_activity", matter_id), entry_id)

    return selection_response(MATTER_ACTIVITY_TRIGGER)


@login_required
@matter_access_required
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
@matter_access_required
@require_POST
def activity_clear_selection(request, matter_id):
    clear_selected_ids(request, get_session_key("selected_matter_activity", matter_id))

    return selection_response(MATTER_ACTIVITY_TRIGGER)


@login_required
@matter_access_required
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
@matter_access_required
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
@matter_access_required
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
