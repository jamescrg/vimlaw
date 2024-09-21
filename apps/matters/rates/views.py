from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import CustomUser
from apps.matters.models import Matter
from apps.matters.proceedings.models import Proceeding
from apps.matters.rates.forms import RateForm
from apps.matters.rates.models import Rate


@login_required
def index(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    rates = Rate.objects.filter(matter=matter).order_by("user__username")

    context = {
        "app": "matters",
        "subapp": "rates",
        "matter": matter,
        "proceeding": proceeding,
        "rates": rates,
    }

    return render(request, "matters/rates/list.html", context)


@login_required
def add(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    # if applicable, process any post data submitted by user
    if request.method == "POST":
        form = RateForm(request.POST)
        if form.is_valid():
            rate = form.save(commit=False)
            rate.matter = matter
            rate.save()
            return redirect(f"/matters/{id}/rates")

    # if no post data has been submitted, show the proceeding form
    else:

        user_list = CustomUser.objects.all().order_by("username")

        for user in user_list:
            matter_rates = Rate.objects.filter(matter=matter, user=user)
            if matter_rates:
                user_list = user_list.exclude(pk=user.pk)

        form = RateForm(initial={"user": request.user})

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
        form = RateForm(request.POST, instance=rate)
        if form.is_valid():
            rate = form.save(commit=False)
            rate.save()
            return redirect(f"/matters/{id}/rates")

    # if no post data has been submitted, show the proceeding form
    else:
        form = RateForm(instance=rate)

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
    return redirect(f"/matters/{matter_id}/rates")
