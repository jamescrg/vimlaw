from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def users_index(request):
    return render(request, "settings/users/index.html", {"subapp": "users"})
