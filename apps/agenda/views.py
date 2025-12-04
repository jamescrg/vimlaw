from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


@login_required
def agenda_redirect(request):
    last_tab = request.session.get("agenda_last_tab", "tasks")
    if last_tab == "events":
        return redirect("agenda:events-index")
    return redirect("agenda:tasks-index")
