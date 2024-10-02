from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def company_index(request):
    return render(request, "settings/company/index.html", {"subapp": "company"})
