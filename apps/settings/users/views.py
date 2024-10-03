from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render

from apps.accounts.models import CustomUser
from apps.settings.users.filters import UserFilter
from apps.settings.users.forms import UserForm
from apps.settings.users.users import get_user_list


@login_required
def users_index(request):
    context = {
        "subapp": "users",
    }

    return render(request, "settings/users/index.html", context)


@login_required
def user_list(request):
    context = get_user_list(request)

    return render(request, "settings/users/user-table.html", context)


@login_required
def user_filter(request):
    if request.method == "POST":
        request.session["user_filter"] = request.POST

        return HttpResponse(status=204, headers={"HX-Trigger": "userListReload"})

    filter_data = request.session.get("user_filter", {})
    filter = UserFilter(
        filter_data, queryset=CustomUser.objects.all().order_by("username")
    )

    return render(request, "settings/users/filter.html", {"filter": filter})


@login_required
def user_sort(request, order):
    filter_data = request.session.get("user_filter", {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["user_filter"] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "userListReload"})


@login_required
def change_role(request, user_id, role):
    CustomUser.objects.filter(id=user_id).update(role=role)

    return HttpResponse(status=204, headers={"HX-Trigger": "userListReload"})


@login_required
def switch_status(request, user_id):
    user = CustomUser.objects.get(id=user_id)

    user.is_active = not user.is_active
    user.save()

    return HttpResponse(status=204, headers={"HX-Trigger": "userListReload"})


@login_required
def edit_user(request, user_id):
    user = CustomUser.objects.get(id=user_id)

    if request.method == "POST":
        form = UserForm(request.POST, instance=user)

        if form.is_valid():
            user = form.save(commit=False)
            user.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "userListReload"})
    else:
        form = UserForm(instance=user)

    context = {
        "form": form,
    }

    return render(request, "settings/users/form.html", context)
