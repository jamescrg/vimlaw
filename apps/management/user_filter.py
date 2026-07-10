from apps.accounts.models import CustomUser


def cycle_user_filter(request, session_key, direction):
    """Advance a tab's user filter to the next/previous active user.

    Shared by the tasks/time/expenses/flat-fees "[ / ]" keyboard shortcut.
    Mirrors the toolbar user-stepper cycle exactly (adjacent_user_ids in
    apps.tasks.tasks): the active users in username order, wrapping at the
    ends, with NO "All users" stop — from All Users the cycle is entered at
    the first/last user. All Users stays reachable from the dropdown.

    `session_key` is the tab's filter dict key ("tasks_filter", "time_filter",
    "expenses_filter"); `direction` is "next" or "prev" (anything but "prev"
    counts as next). Mutates request.session[session_key]["user"] in place.
    """
    user_ids = list(
        CustomUser.objects.filter(is_active=True)
        .order_by("username")
        .values_list("id", flat=True)
    )
    if not user_ids:
        return

    filter_data = dict(request.session.get(session_key, {}))
    current = filter_data.get("user")
    current = int(current) if current not in (None, "", 0, "0") else None
    try:
        idx = user_ids.index(current)
    except ValueError:
        idx = None

    step = -1 if direction == "prev" else 1
    if idx is None:
        # From All Users (or an unknown/inactive id), enter the cycle at the
        # last/first user — same as the stepper chevrons.
        new_user = user_ids[-1] if step == -1 else user_ids[0]
    else:
        new_user = user_ids[(idx + step) % len(user_ids)]

    filter_data["user"] = new_user
    request.session[session_key] = filter_data
    request.session.modified = True
