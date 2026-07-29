from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render

from apps.intakes.models import IntakeEmailTemplate
from apps.settings.intake_emails.forms import IntakeEmailTemplateForm


@login_required
def intake_emails_index(request):
    context = {
        "app": "settings",
        "subapp": "intake-emails",
        "email_templates": IntakeEmailTemplate.objects.all(),
    }
    return render(request, "settings/intake-emails/index.html", context)


@login_required
def email_template_list(request):
    context = {"email_templates": IntakeEmailTemplate.objects.all()}
    return render(request, "settings/intake-emails/table.html", context)


@login_required
def add_email_template(request):
    if request.method == "POST":
        form = IntakeEmailTemplateForm(request.POST)
        if form.is_valid():
            form.save()
            return HttpResponse(
                status=204, headers={"HX-Trigger": "intakeEmailTemplateListReload"}
            )
    else:
        form = IntakeEmailTemplateForm()
    return render(request, "settings/intake-emails/form.html", {"form": form})


@login_required
def edit_email_template(request, template_id):
    template = IntakeEmailTemplate.objects.get(id=template_id)
    if request.method == "POST":
        form = IntakeEmailTemplateForm(request.POST, instance=template)
        if form.is_valid():
            form.save()
            return HttpResponse(
                status=204, headers={"HX-Trigger": "intakeEmailTemplateListReload"}
            )
    else:
        form = IntakeEmailTemplateForm(instance=template)
    return render(
        request,
        "settings/intake-emails/form.html",
        {"form": form, "email_template": template},
    )


@login_required
def delete_email_template(request, template_id):
    IntakeEmailTemplate.objects.get(id=template_id).delete()
    return HttpResponse(
        status=204, headers={"HX-Trigger": "intakeEmailTemplateListReload"}
    )
