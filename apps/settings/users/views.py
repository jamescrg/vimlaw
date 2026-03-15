from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import render

from apps.accounts.models import CustomUser
from apps.matters.models import Matter
from apps.settings.users.filters import UserFilter
from apps.settings.users.forms import CreateUserForm, UserForm
from apps.settings.users.users import DEFAULT_USER_FILTER, get_user_list


@login_required
def users_index(request):
    context = get_user_list(request)

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

    # If no filter data exists, apply default filter
    if not filter_data:
        filter_data = DEFAULT_USER_FILTER

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
def add_user(request):
    if request.method == "POST":
        form = CreateUserForm(request.POST)

        if form.is_valid():
            form.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "userListReload"})
    else:
        form = CreateUserForm()

    context = {
        "form": form,
    }

    return render(request, "settings/users/new-user.html", context)


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


@login_required
def toggle_permission(request, user_id, perm):
    if not request.user.is_admin:
        return HttpResponseForbidden()

    VALID_PERMS = [
        "perm_all_matters",
        "perm_financial",
        "perm_intakes",
        "perm_reports",
        "perm_research",
    ]
    if perm not in VALID_PERMS:
        return HttpResponseBadRequest()

    user = CustomUser.objects.get(id=user_id)
    setattr(user, perm, not getattr(user, perm))
    user.save(update_fields=[perm])

    return HttpResponse(status=204, headers={"HX-Trigger": "userListReload"})


@login_required
def matter_assignments(request, user_id):
    """Render the matter assignment modal for a user."""
    if not request.user.is_admin:
        return HttpResponseForbidden()
    target_user = CustomUser.objects.get(id=user_id)
    assigned = target_user.assigned_matters.filter(status="Open").order_by("name")
    assigned_ids = set(assigned.values_list("id", flat=True))
    unassigned = (
        Matter.objects.filter(status="Open")
        .exclude(id__in=assigned_ids)
        .order_by("name")
    )
    context = {
        "target_user": target_user,
        "assigned": assigned,
        "unassigned": unassigned,
    }
    return render(request, "settings/users/matter-assignments.html", context)


@login_required
def toggle_matter_assignment(request, user_id, matter_id):
    """Toggle a matter assignment for a user, then re-render modal body."""
    if not request.user.is_admin:
        return HttpResponseForbidden()
    target_user = CustomUser.objects.get(id=user_id)
    matter = Matter.objects.get(id=matter_id)
    if target_user.assigned_matters.filter(id=matter_id).exists():
        target_user.assigned_matters.remove(matter)
    else:
        target_user.assigned_matters.add(matter)
    # Re-render just the body partial
    assigned = target_user.assigned_matters.filter(status="Open").order_by("name")
    assigned_ids = set(assigned.values_list("id", flat=True))
    unassigned = (
        Matter.objects.filter(status="Open")
        .exclude(id__in=assigned_ids)
        .order_by("name")
    )
    context = {
        "target_user": target_user,
        "assigned": assigned,
        "unassigned": unassigned,
    }
    return render(request, "settings/users/matter-assignments-body.html", context)
