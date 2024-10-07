from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def index(request):
    context = {
        "app": "settings",
        "subapp": "session",
    }

    return render(request, "settings/session/index.html", context)
