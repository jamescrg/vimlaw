from django.http import HttpResponse


def get_session_key(prefix, scope_id=None):
    """Generate a scoped session key."""
    if scope_id is not None:
        return f"{prefix}_{scope_id}"

    return prefix


def get_selected_ids(request, session_key):
    """Return the current list of selected IDs from the session."""
    return request.session.get(session_key, [])


def toggle_id(request, session_key, obj_id):
    """Add obj_id to selection if absent, remove if present."""
    selected = request.session.get(session_key, [])

    if obj_id in selected:
        selected.remove(obj_id)
    else:
        selected.append(obj_id)

    request.session[session_key] = selected


def select_all_ids(request, session_key, visible_ids):
    """If all visible IDs are selected, deselect all. Otherwise select all visible."""
    selected = request.session.get(session_key, [])
    all_selected = bool(visible_ids) and all(i in selected for i in visible_ids)

    if all_selected:
        request.session[session_key] = []
    else:
        request.session[session_key] = list(set(selected + visible_ids))


def clear_selected_ids(request, session_key):
    """Clear all selections."""
    request.session[session_key] = []


def all_visible_selected(selected_ids, visible_ids):
    """Return True if every visible ID is in selected_ids."""
    return bool(visible_ids) and all(i in selected_ids for i in visible_ids)


def selection_response(htmx_trigger):
    """Return the standard 204 response that triggers an HTMX list refresh."""
    return HttpResponse(status=204, headers={"HX-Trigger": htmx_trigger})
