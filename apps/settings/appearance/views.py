from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def appearance_index(request):
    context = {
        "subapp": "appearance",
    }
    return render(request, "settings/appearance/index.html", context)
