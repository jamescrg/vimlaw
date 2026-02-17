from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.settings.company.forms import CompanyForm
from apps.settings.models import Company


@login_required
def company_index(request):
    company = Company.objects.first()
    message = None

    if request.method == "POST":
        form = CompanyForm(request.POST, request.FILES, instance=company)
        if form.is_valid():
            company = form.save()
            message = "Company updated successfully"
            form = CompanyForm(instance=company)
        return render(
            request,
            "settings/company/form.html",
            {"form": form, "company": company, "message": message},
        )

    form = CompanyForm(instance=company)
    return render(
        request,
        "settings/company/index.html",
        {"subapp": "company", "form": form, "company": company},
    )
