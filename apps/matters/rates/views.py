from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.accounts.models import CustomUser
from apps.matters.ledger.get_ledger_data import get_ledger_data
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding
from apps.matters.rates.forms import RateForm
from apps.matters.rates.models import Rate
from apps.trust.trust import get_confirmed_client_balance


@login_required
def rate_index(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id, primary=True).first()

    rates = Rate.objects.filter(matter=matter).order_by("user__username")

    # Get client trust balance
    client_trust_balance = 0
    if matter.client:
        client_trust_balance = get_confirmed_client_balance(matter.client.id)

    # Get balance due from ledger
    ledger_data = get_ledger_data(matter)
    balance_due = ledger_data.get("balance_due", 0)

    context = {
        "app": "matters",
        "subapp": "rates",
        "matter": matter,
        "proceeding": proceeding,
        "rates": rates,
        "client_trust_balance": client_trust_balance,
        "balance_due": balance_due,
    }

    return render(request, "matters/rates/main.html", context)


@login_required
def rate_list(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    rates = Rate.objects.filter(matter=matter).order_by("user__username")

    # Get client trust balance
    client_trust_balance = 0
    if matter.client:
        client_trust_balance = get_confirmed_client_balance(matter.client.id)

    # Get balance due from ledger
    ledger_data = get_ledger_data(matter)
    balance_due = ledger_data.get("balance_due", 0)

    context = {
        "app": "matters",
        "subapp": "rates",
        "matter": matter,
        "proceeding": proceeding,
        "rates": rates,
        "client_trust_balance": client_trust_balance,
        "balance_due": balance_due,
    }

    return render(request, "matters/rates/list.html", context)


@login_required
def add(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = RateForm(request.POST, use_required_attribute=False)
        if form.is_valid():
            rate = form.save(commit=False)
            rate.matter = matter
            rate.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "matterRateChanged"})

    # if no post data has been submitted, show the proceeding form
    else:
        user_list = CustomUser.objects.all().order_by("username")

        for user in user_list:
            matter_rates = Rate.objects.filter(matter=matter, user=user)
            if matter_rates:
                user_list = user_list.exclude(pk=user.pk)

        form = RateForm(initial={"user": request.user}, use_required_attribute=False)

        # set the list of potential users
        for user in user_list:
            user.username = user.username.title()

    context = {
        "app": "matters",
        "subapp": "rates",
        "matter": matter,
        "proceeding": proceeding,
        "edit": False,
        "add": True,
        "action": f"/matters/{id}/rates/add",
        "form": form,
    }

    return render(request, "matters/rates/form.html", context)


@login_required
def edit(request, id, rate_id):
    matter = get_object_or_404(Matter, pk=id)

    rate = get_object_or_404(Rate, pk=rate_id)

    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = RateForm(request.POST, instance=rate, use_required_attribute=False)
        if form.is_valid():
            rate = form.save(commit=False)
            rate.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "matterRateChanged"})

    # if no post data has been submitted, show the proceeding form
    else:
        form = RateForm(instance=rate, use_required_attribute=False)

    context = {
        "app": "matters",
        "subapp": "rates",
        "matter": matter,
        "rate": rate,
        "edit": True,
        "add": False,
        "action": f"/matters/{id}/rates/{rate_id}/edit",
        "form": form,
    }

    return render(request, "matters/rates/form.html", context)


@login_required
def delete(request, matter_id, rate_id):
    rate = get_object_or_404(Rate, pk=rate_id)
    rate.delete()

    return HttpResponse(status=204, headers={"HX-Trigger": "matterRateChanged"})
