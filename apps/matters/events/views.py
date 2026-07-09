from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.accounts.access import matter_access_required
from apps.matters.events.get_event_data import get_event_data
from apps.matters.models import Matter


def _view_mode(request):
    """List/calendar toggle for the matter Events tab, shared across matters
    (mirrors the main calendar's events_view_mode session flag)."""
    return request.session.get("matter_events_view_mode", "calendar")


def _calendar_context(request, matter):
    """Context for the calendar partial: no table data, just the toolbar's
    filter state."""
    status_session_key = f"matter_events_filter_{matter.id}"
    return {
        "matter": matter,
        "view_mode": "calendar",
        "events_filter_status": request.session.get(status_session_key, "Pending"),
    }


@login_required
@matter_access_required
def events_index(request, id):
    matter = get_object_or_404(Matter, pk=id)
    view_mode = _view_mode(request)

    if view_mode == "calendar":
        event_data = _calendar_context(request, matter)
    else:
        event_data = get_event_data(request, matter) | {"view_mode": view_mode}

    context = {
        "app": "matters",
        "subapp": "events",
        "matter": matter,
        "tab_template": "matters/events/tab.html",
    } | event_data

    return render(request, "matters/includes/tab-page.html", context)


@login_required
@matter_access_required
def events_list(request, id):
    """The #matterEvents container body — list or calendar per the session
    view mode."""
    matter = get_object_or_404(Matter, pk=id)
    view_mode = _view_mode(request)

    if view_mode == "calendar":
        return render(
            request,
            "matters/events/calendar.html",
            _calendar_context(request, matter),
        )

    context = {
        "app": "matters",
        "subapp": "events",
        "matter": matter,
        "view_mode": view_mode,
    } | get_event_data(request, matter)

    return render(request, "matters/events/list.html", context)


@login_required
@matter_access_required
def events_view_mode(request, id, mode):
    """Toggle between list and calendar views; persist in session."""
    if mode in ("list", "calendar"):
        request.session["matter_events_view_mode"] = mode
        request.session.modified = True
    return HttpResponse(status=204, headers={"HX-Trigger": "eventsViewChanged"})


@login_required
@matter_access_required
def events_filter_status(request, id, status):
    """Save the status pick, re-render the dropdown in place, and let the
    matterEventChanged trigger refresh the list (or refetch the calendar)."""
    matter = get_object_or_404(Matter, pk=id)
    session_key = f"matter_events_filter_{matter.id}"
    request.session[session_key] = status if status else ""
    request.session.modified = True

    response = render(
        request,
        "matters/events/status-dropdown.html",
        {"matter": matter, "events_filter_status": status},
    )
    response["HX-Trigger"] = "matterEventChanged"
    return response


@login_required
@matter_access_required
def events_filter_sort(request, id, order):
    matter = get_object_or_404(Matter, pk=id)
    session_key = f"matter_events_sort_{matter.id}"

    current_order = request.session.get(session_key, "date")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    request.session[session_key] = new_order
    request.session.modified = True

    return HttpResponse(status=204, headers={"HX-Trigger": "matterEventChanged"})
