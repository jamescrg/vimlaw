from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


@login_required
def clear_filters(request, session_key):
    """
    Clear filter data from the session
    """
    request.session[session_key] = {}

    return redirect(request.META.get("HTTP_REFERER", "/"))
