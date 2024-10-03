from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render

from apps.settings.profile.forms import ProfileForm


@login_required
def profile_index(request):
    context = {
        "subapp": "profile",
    }
    return render(request, "settings/profile/index.html", context)


@login_required
def personal_profile(request):
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=request.user)

        if form.is_valid():
            profile = form.save(commit=False)
            profile.save()

            return HttpResponse("Profile updated successfully")
    else:
        form = ProfileForm(instance=request.user)

    context = {
        "user": request.user,
        "form": form,
    }

    return render(request, "settings/profile/profile.html", context)
