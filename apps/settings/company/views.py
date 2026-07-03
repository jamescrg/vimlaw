from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.settings.company.forms import (
    CompanyForm,
    CompanyResearchForm,
)
from apps.settings.models import Company
from utils.toasts import toast_success


@login_required
def company_index(request):
    """Company settings page: Company Info + Research subsections.

    The Company Info form posts here; Research posts to its own endpoint. Each
    subsection re-renders on save and fires a success toast.
    """
    company = Company.objects.first()

    if request.method == "POST":
        form = CompanyForm(request.POST, request.FILES, instance=company)
        saved = form.is_valid()
        if saved:
            company = form.save()
            form = CompanyForm(instance=company)
        response = render(
            request,
            "settings/company/form.html",
            {"form": form, "company": company},
        )
        if saved:
            toast_success(response, "Company details updated")
        return response

    return render(
        request,
        "settings/company/index.html",
        {
            "subapp": "company",
            "form": CompanyForm(instance=company),
            "research_form": CompanyResearchForm(instance=company),
            "company": company,
        },
    )


@login_required
def company_research(request):
    company = Company.objects.first()
    form = CompanyResearchForm(request.POST or None, instance=company)
    saved = request.method == "POST" and form.is_valid()
    if saved:
        company = form.save()
        form = CompanyResearchForm(instance=company)
    response = render(
        request,
        "settings/company/research.html",
        {"research_form": form, "company": company},
    )
    if saved:
        toast_success(response, "Research settings updated")
    return response
