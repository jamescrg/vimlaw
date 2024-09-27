from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def profile_index(request):
    return render(request, "settings/profile/index.html", {"subapp": "profile"})
