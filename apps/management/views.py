from django.contrib.auth.decorators import login_required
from django.http.response import HttpResponse
from django.shortcuts import redirect


@login_required
def clear_filters(request, session_key, trigger=None):
    """
    Clear filter data from the session
    """
    request.session[session_key] = {}

    if trigger:
        return HttpResponse(status=204, headers={"HX-Trigger": trigger})

    return redirect(request.META.get("HTTP_REFERER", "/"))
