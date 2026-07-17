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
from apps.activity.models import ActivityCategory
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
from apps.matters.generate_fee_claim_report import generate_fee_claim_report
from apps.matters.models import Matter
from utils.toasts import toast_warning


def _category_filter_value(request, matter_id):
    """The tab's category filter: "" = all, "none" = uncategorized, else a
    category id. Validated against the matter so a stale id can't stick."""
    value = str(request.session.get(f"matter_activity_category_{matter_id}", ""))
    if value and value != "none":
        if not ActivityCategory.objects.filter(id=value, matter_id=matter_id).exists():
            return ""
    return value


def _apply_category_filter(queryset, value, field="category"):
    if value == "none":
        return queryset.filter(**{f"{field}__isnull": True})
    if value:
        return queryset.filter(**{f"{field}_id": value})
    return queryset


def get_category_totals(matter, uncategorized_claimed=True):
    """Per-category time (gross/comp/net fees) and net expense totals for the
    categories sub-view, plus an uncategorized bucket and claimed/unclaimed/
    total rollups (uncategorized counts per the user's preference). Summed in
    Python like the fee claim report — per-matter volumes are small and two
    reverse-FK aggregates in one queryset would multiply join rows."""

    def time_totals(entries):
        gross = sum(e.fee for e in entries)
        comp = sum(e.fee for e in entries if e.comp)
        return gross, comp, gross - comp

    def expense_total(expenses):
        return sum(x.amount for x in expenses) - sum(
            x.amount for x in expenses if x.comp
        )

    rows = []
    for category in matter.activity_categories.all():
        # Matter guard mirrors the fee claim report: a category left on an
        # entry that moved matters doesn't count here.
        entries = list(category.time_entries.filter(matter=matter))
        gross, comp, net = time_totals(entries)
        expenses = expense_total(category.expense_entries.filter(matter=matter))
        rows.append(
            {
                "category": category,
                "entry_count": len(entries),
                "time_gross": gross,
                "time_comp": comp,
                "time_net": net,
                "expenses": expenses,
                "total": net + expenses,
            }
        )

    entries = list(TimeEntry.objects.filter(matter=matter, category__isnull=True))
    gross, comp, net = time_totals(entries)
    expenses = expense_total(
        ExpenseEntry.objects.filter(matter=matter, activity_category__isnull=True)
    )
    uncategorized = {
        "entry_count": len(entries),
        "time_gross": gross,
        "time_comp": comp,
        "time_net": net,
        "expenses": expenses,
        "total": net + expenses,
    }

    claimed_rows = [r for r in rows if r["category"].claimed]
    unclaimed_rows = [r for r in rows if not r["category"].claimed]
    (claimed_rows if uncategorized_claimed else unclaimed_rows).append(uncategorized)

    def bucket(bucket_rows):
        keys = ("time_gross", "time_comp", "time_net", "expenses", "total")
        return {key: sum(r[key] for r in bucket_rows) for key in keys}

    claimed = bucket(claimed_rows)
    unclaimed = bucket(unclaimed_rows)
    all_activity = {key: claimed[key] + unclaimed[key] for key in claimed}

    return {
        "category_rows": rows,
        "uncategorized": uncategorized,
        "uncategorized_claimed": uncategorized_claimed,
        "category_totals": {
            "claimed": claimed,
            "unclaimed": unclaimed,
            "all": all_activity,
        },
    }


def get_matter_activity_data(request, matter):
    """Context for the matter activity subtab, honoring the Time/Expenses toggle
    (session `matter_activity_view`, default 'time'). Expenses is a simple
    read-only list; Time keeps the existing sort/paginate/select machinery."""
    view = request.session.get("matter_activity_view", "time")

    category_filter = _category_filter_value(request, matter.id)
    selected_category = None
    if category_filter and category_filter != "none":
        selected_category = ActivityCategory.objects.filter(id=category_filter).first()

    filter_context = {
        "categories": matter.activity_categories.all(),
        "category_filter": category_filter,
        "selected_category": selected_category,
    }

    if view == "categories":
        return {
            "matter": matter,
            "activity_view": "categories",
            **get_category_totals(matter, matter.uncategorized_claimed),
            **filter_context,
        }

    if view == "expenses":
        expense_entries = list(
            _apply_category_filter(
                ExpenseEntry.objects.filter(matter=matter),
                category_filter,
                field="activity_category",
            )
            .select_related("user", "matter", "activity_category")
            .order_by("-date", "-id")
        )
        return {
            "matter": matter,
            "activity_view": "expenses",
            "expense_entries": expense_entries,
            "expense_summary": calculate_expense_summary(expense_entries),
            **filter_context,
        }

    sort_order = request.session.get("matter_activity_sort", "-id")
    entries = (
        _apply_category_filter(TimeEntry.objects.filter(matter=matter), category_filter)
        .select_related("category")
        .order_by(sort_order)
    )
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
        **filter_context,
    }


@login_required
@matter_access_required
@require_POST
def activity_view(request, id, view):
    """Switch the subtab between the time and expenses lists. The #rates panel
    reloads via the matterActivityChanged trigger."""
    get_object_or_404(Matter, pk=id)
    request.session["matter_activity_view"] = (
        view if view in ("expenses", "categories") else "time"
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
@require_POST
def activity_toggle_uncategorized_claimed(request, id):
    """Flip whether uncategorized time counts as claimed in the totals.
    Stored on the matter so the whole team sees the same rollup."""
    matter = get_object_or_404(Matter, pk=id)
    matter.uncategorized_claimed = not matter.uncategorized_claimed
    matter.save()
    return selection_response(MATTER_ACTIVITY_TRIGGER)


@login_required
@matter_access_required
@require_POST
def activity_filter_category(request, id):
    """Filter the tab to one category ("" = all, "none" = uncategorized).
    Optionally jumps to a sub-view at the same time — the categories table's
    entry counts link to the filtered Time list this way."""
    get_object_or_404(Matter, pk=id)
    request.session[f"matter_activity_category_{id}"] = request.POST.get("category", "")

    view = request.POST.get("view", "")
    if view in ("time", "expenses"):
        request.session["matter_activity_view"] = view

    return selection_response(MATTER_ACTIVITY_TRIGGER)


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


@login_required
@matter_access_required
def fee_claim_report_modal(request, id):
    """Options modal shown before generating the fee claim report."""
    matter = get_object_or_404(Matter, pk=id)
    return render(request, "matters/fee-claim-modal.html", {"matter": matter})


@login_required
@matter_access_required
def fee_claim_report(request, id):
    matter = get_object_or_404(Matter, pk=id)

    # The chosen options become the matter's new defaults (team-wide).
    include_unclaimed = request.GET.get("include_unclaimed") == "true"
    show_entries = request.GET.get("show_entries") == "true"
    group_by_category = request.GET.get("group_by_category") == "true"
    if (
        matter.report_include_unclaimed != include_unclaimed
        or matter.report_show_entries != show_entries
        or matter.report_group_by_category != group_by_category
    ):
        matter.report_include_unclaimed = include_unclaimed
        matter.report_show_entries = show_entries
        matter.report_group_by_category = group_by_category
        matter.save()

    file = generate_fee_claim_report(
        matter, request, include_unclaimed, show_entries, group_by_category
    )

    current_date = datetime.now().strftime("%Y-%m-%d")

    with open(file.name, "rb") as pdf:
        response = HttpResponse(pdf.read(), content_type="application/pdf")
        filename = (
            f'filename="Fee and Expense Report - {matter.name} - {current_date}.pdf"'
        )
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
    # Mirror the tab's category filter so "select all" matches what's shown.
    entries = _apply_category_filter(
        TimeEntry.objects.filter(matter=matter_id),
        _category_filter_value(request, matter_id),
    ).order_by(sort_order)

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
            entries = TimeEntry.objects.filter(id__in=selected_entries).select_related(
                "invoice"
            )

            locked = 0
            for entry in entries:
                # Entries on a finalized invoice are no longer editable —
                # moving one would silently pull it off the invoice.
                if entry.locked:
                    locked += 1
                    continue

                # Clear invoice if matter changes
                entry.matter = new_matter
                entry.invoice = None

                entry.save()

            clear_selected_ids(request, key)
            response = HttpResponse(
                status=204, headers={"HX-Trigger": MATTER_ACTIVITY_TRIGGER}
            )
            if locked:
                toast_warning(
                    response,
                    f"Skipped {locked} {'entry' if locked == 1 else 'entries'} "
                    "on a finalized invoice.",
                )
            return response

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
            entries = TimeEntry.objects.filter(id__in=selected_entries).select_related(
                "invoice"
            )
            comp_bool = comp_value == "true"

            locked = 0
            for entry in entries:
                # Entries on a finalized invoice are no longer editable.
                if entry.locked:
                    locked += 1
                    continue
                entry.comp = comp_bool
                entry.save()

            clear_selected_ids(request, key)
            response = HttpResponse(
                status=204, headers={"HX-Trigger": MATTER_ACTIVITY_TRIGGER}
            )
            if locked:
                toast_warning(
                    response,
                    f"Skipped {locked} {'entry' if locked == 1 else 'entries'} "
                    "on a finalized invoice.",
                )
            return response

    context = {
        "selected_count": len(selected_entries),
        "entry_type": "time",
        "matter_id": matter_id,
    }

    return render(request, "matters/activity/bulk-comp-form.html", context)


@login_required
@matter_access_required
@require_POST
def activity_bulk_set_category(request, matter_id):
    """Set (or clear, with an empty category_id) the category on all
    selected time entries. Allowed on billing-locked entries — coding never
    touches invoiced amounts."""
    key = get_session_key("selected_matter_activity", matter_id)
    selected_entries = get_selected_ids(request, key)

    if not selected_entries:
        return HttpResponse(status=400, content="No time entries selected.")

    category_id = request.POST.get("category_id", "")
    category = None
    if category_id:
        category = get_object_or_404(
            ActivityCategory, id=category_id, matter_id=matter_id
        )

    entries = TimeEntry.objects.filter(id__in=selected_entries)
    for entry in entries:
        entry.category = category
        entry.save()

    clear_selected_ids(request, key)
    return HttpResponse(status=204, headers={"HX-Trigger": MATTER_ACTIVITY_TRIGGER})
