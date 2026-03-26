from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def index(request):
    context = {
        "app": "settings",
        "subapp": "session",
    }

    return render(request, "settings/session/index.html", context)


@login_required
def keyboard_shortcuts(request):
    return render(request, "settings/keyboard-shortcuts-modal.html")
