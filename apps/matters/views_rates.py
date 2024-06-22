
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.shortcuts import redirect
from django.shortcuts import get_object_or_404

from apps.matters.models import Matter
from apps.matters.models import Proceeding
from apps.matters.models import Rate
from apps.matters.forms import RateForm
from accounts.models import CustomUser


@login_required
def index(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(
        matter=matter.id).order_by("-id").first()

    rates = Rate.objects.filter(matter=matter)

    context = {
        "page": "matters",
        "submodule": "rates",
        "matter": matter,
        "proceeding": proceeding,
        "rates": rates,
    }

    return render(request, "matters/rates/list.html", context)


@login_required
def add(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(
        matter=matter.id).order_by("-id").first()

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
        form.fields["user"].queryset = user_list

    context = {
        "page": "matters",
        "submodule": "rates",
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
    proceeding = Proceeding.objects.filter(
        matter=matter.id).order_by("-id").first()

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
        "page": "matters",
        "submodule": "rates",
        "matter": matter,
        "rate": rate,
        "edit": True,
        "add": False,
        "action": f"/matters/{id}/rates/{rate_id}/edit",
        "form": form,
    }

    return render(request, "matters/rates/form.html", context)


@login_required
def delete(request, id, rate_id):
    rate = get_object_or_404(Rate, pk=rate_id)
    rate.delete()
    return redirect(f"/matters/{id}/rates")
