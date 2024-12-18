import json

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.billing.credits.filters import CreditsFilter
from apps.billing.credits.forms import CreditsForm
from apps.billing.credits.get_credits_data import get_credits_data
from apps.billing.credits.models import Credit
from apps.matters.models import Matter


@login_required
def credits_index(request):
    credits_data = get_credits_data(request)

    context = {
        "app": "billing",
        "subapp": "credits",
    } | credits_data

    return render(request, "billing/credits/main.html", context)


@login_required
def credits_list(request):
    credits_data = get_credits_data(request)

    context = {
        "app": "billing",
        "subapp": "credits",
    } | credits_data

    return render(request, "billing/credits/list.html", context)


@login_required
def credits_add(request):
    matters = Matter.objects.exclude(status="Closed").order_by("name")

    form = CreditsForm(request.POST or None, use_required_attribute=False)
    form.fields["matter"].queryset = matters

    if request.method == "POST" and form.is_valid():
        form.save()

        return HttpResponse(status=204, headers={"HX-Trigger": "creditsChanged"})

    return render(request, "billing/credits/form.html", {"form": form})


@login_required
def credits_edit(request, pk):
    credit = get_object_or_404(Credit, pk=pk)

    matters = Matter.objects.exclude(status="Closed").order_by("name")

    if request.method == "POST":
        form = CreditsForm(request.POST, instance=credit, use_required_attribute=False)

        if form.is_valid():
            form.save()

            return HttpResponse(
                status=204,
                headers={
                    "HX-Trigger": json.dumps(
                        {"creditsChanged": "", "matterLedgerChanged": ""}
                    )
                },
            )
    else:
        form = CreditsForm(instance=credit, use_required_attribute=False)

    form.fields["matter"].queryset = matters

    return render(
        request, "billing/credits/edit.html", {"form": form, "credit": credit}
    )


@login_required
def credits_delete(_, pk):
    Credit.objects.get(pk=pk).delete()

    return HttpResponse(
        status=204,
        headers={
            "HX-Trigger": json.dumps({"creditsChanged": "", "matterLedgerChanged": ""})
        },
    )


@login_required
def order_by_credits(request, order):
    filter_data = request.session.get("credits_filter", {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["credits_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "creditsChanged"})


@login_required
def credits_filter(request):
    def get_filter(request):
        filter_data = request.session.get("credits_filter", request.POST)

        if filter_data:
            return CreditsFilter(
                filter_data,
                queryset=Credit.objects.all()
                .select_related("matter")
                .order_by("-date", "-id"),
            )
        else:
            default_filter = {"order_by": "-date"}

        return CreditsFilter(
            default_filter,
            queryset=Credit.objects.all()
            .select_related("matter")
            .order_by("-date", "-id"),
        )

    if request.method == "POST":
        request.session["credits_filter"] = request.POST

        return HttpResponse(status=204, headers={"HX-Trigger": "creditsChanged"})
    else:
        filter = get_filter(request)

        return render(request, "billing/credits/filter.html", {"filter": filter})
