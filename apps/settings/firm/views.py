from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.settings.firm.forms import FirmForm, FirmLogoForm
from apps.settings.models import Firm
from utils.toasts import toast_success


@login_required
def firm_index(request):
    """Firm settings page: one form for contact details, invoice BCC, and
    research jurisdiction. Re-renders on save and fires a toast. The logo
    uploads/removes on its own (see the logo endpoints below)."""
    firm = Firm.objects.first()

    if request.method == "POST":
        form = FirmForm(request.POST, instance=firm)
        saved = form.is_valid()
        if saved:
            firm = form.save()
            form = FirmForm(instance=firm)
        response = render(
            request,
            "settings/firm/form.html",
            {"form": form, "logo_form": FirmLogoForm(), "firm": firm},
        )
        if saved:
            toast_success(response, "Firm details updated")
        return response

    return render(
        request,
        "settings/firm/index.html",
        {
            "subapp": "firm",
            "form": FirmForm(instance=firm),
            "logo_form": FirmLogoForm(),
            "firm": firm,
        },
    )


def _render_logo(request, firm, logo_form=None):
    """Render just the logo row/upload partial (swapped into #firm-logo)."""
    return render(
        request,
        "settings/firm/logo.html",
        {"firm": firm, "logo_form": logo_form or FirmLogoForm()},
    )


@login_required
def firm_upload_logo(request):
    """Store the newly chosen logo, then re-render the logo partial."""
    firm = Firm.objects.first() or Firm.objects.create(name="")
    form = FirmLogoForm(request.POST, request.FILES, instance=firm)
    if form.is_valid():
        firm = form.save()
        response = _render_logo(request, firm)
        toast_success(response, "Logo added")
        return response
    return _render_logo(request, firm, logo_form=form)


@login_required
def firm_remove_logo(request):
    """Clear the firm logo, then re-render the logo partial."""
    firm = Firm.objects.first()
    if request.method == "POST" and firm and firm.logo:
        firm.logo.delete(save=False)
        firm.logo = None
        firm.save()
    response = _render_logo(request, firm)
    toast_success(response, "Logo removed")
    return response
