from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def index(request):

    context = {
        "app": "documents",
    }

    return render(request, "documents/main.html", context)
