from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render

from apps.settings.company.forms import FirmProfileForm
from apps.settings.models import FirmProfile


@login_required
def company_index(request):
    firm = FirmProfile.get_instance()
    context = {
        "subapp": "company",
        "firm": firm,
    }
    return render(request, "settings/company/index.html", context)


@login_required
def company_profile(request):
    """Returns the firm profile partial for HTMX reload."""
    firm = FirmProfile.get_instance()
    return render(request, "settings/company/profile.html", {"firm": firm})


@login_required
def edit_firm_profile(request):
    firm = FirmProfile.get_instance()

    if request.method == "POST":
        form = FirmProfileForm(request.POST, request.FILES, instance=firm)

        if form.is_valid():
            form.save()
            return HttpResponse(status=204, headers={"HX-Trigger": "firmProfileReload"})
    else:
        form = FirmProfileForm(instance=firm)

    context = {
        "form": form,
        "firm": firm,
    }
    return render(request, "settings/company/form.html", context)
