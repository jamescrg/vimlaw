import json

from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import ProtectedError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from apps.matters.models import Group, Role
from apps.settings.contacts.forms import GroupForm, RoleForm


@login_required
def contacts_index(request):
    # Get filter from session, default to "active"
    group_filter = request.session.get("settings_group_filter", "active")
    role_filter = request.session.get("settings_role_filter", "active")

    groups = Group.objects.all().order_by("order")
    if group_filter == "active":
        groups = groups.filter(is_active=True)
    elif group_filter == "inactive":
        groups = groups.filter(is_active=False)

    roles = Role.objects.all().order_by("name")
    if role_filter == "active":
        roles = roles.filter(is_active=True)
    elif role_filter == "inactive":
        roles = roles.filter(is_active=False)

    context = {
        "subapp": "contacts",
        "roles": roles,
        "groups": groups,
        "group_filter": group_filter,
        "role_filter": role_filter,
    }

    return render(request, "settings/contacts/index.html", context)


@login_required
def role_list(request):
    role_filter = request.session.get("settings_role_filter", "active")

    roles = Role.objects.all().order_by("name")
    if role_filter == "active":
        roles = roles.filter(is_active=True)
    elif role_filter == "inactive":
        roles = roles.filter(is_active=False)

    context = {
        "roles": roles,
        "role_filter": role_filter,
    }

    return render(request, "settings/contacts/role-table.html", context)


@login_required
def role_filter(request, status):
    request.session["settings_role_filter"] = status
    return HttpResponse(status=204, headers={"HX-Trigger": "roleListReload"})


@login_required
def add_role(request):
    if request.method == "POST":
        form = RoleForm(request.POST)

        if form.is_valid():
            form.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "roleListReload"})
    else:
        form = RoleForm()

    context = {
        "form": form,
    }

    return render(request, "settings/contacts/role-form.html", context)


@login_required
def edit_role(request, role_id):
    role = Role.objects.get(id=role_id)

    if request.method == "POST":
        form = RoleForm(request.POST, instance=role)

        if form.is_valid():
            form.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "roleListReload"})
    else:
        form = RoleForm(instance=role)

    context = {
        "form": form,
        "role": role,
    }

    return render(request, "settings/contacts/role-form.html", context)


@login_required
def delete_role(request, role_id):
    try:
        Role.objects.get(id=role_id).delete()
        return HttpResponse(status=204, headers={"HX-Trigger": "roleListReload"})
    except ProtectedError:
        error_message = "Cannot delete role: it is in use by one or more relationships."
        trigger = f'{{"showToast": {{"message": "{error_message}", "type": "error"}}}}'
        return HttpResponse(status=200, headers={"HX-Trigger": trigger})


# Group views


@login_required
def group_list(request):
    group_filter = request.session.get("settings_group_filter", "active")

    groups = Group.objects.all().order_by("order")
    if group_filter == "active":
        groups = groups.filter(is_active=True)
    elif group_filter == "inactive":
        groups = groups.filter(is_active=False)

    context = {
        "groups": groups,
        "group_filter": group_filter,
    }

    return render(request, "settings/contacts/group-table.html", context)


@login_required
def group_filter(request, status):
    request.session["settings_group_filter"] = status
    return HttpResponse(status=204, headers={"HX-Trigger": "groupListReload"})


@login_required
def add_group(request):
    if request.method == "POST":
        form = GroupForm(request.POST)

        if form.is_valid():
            group = form.save(commit=False)
            # Auto-assign order: new groups go to the end
            max_order = Group.objects.aggregate(models.Max("order"))["order__max"] or 0
            group.order = max_order + 1
            group.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "groupListReload"})
    else:
        form = GroupForm()

    context = {
        "form": form,
    }

    return render(request, "settings/contacts/group-form.html", context)


@login_required
def edit_group(request, group_id):
    group = Group.objects.get(id=group_id)

    if request.method == "POST":
        form = GroupForm(request.POST, instance=group)

        if form.is_valid():
            form.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "groupListReload"})
    else:
        form = GroupForm(instance=group)

    context = {
        "form": form,
        "group": group,
    }

    return render(request, "settings/contacts/group-form.html", context)


@login_required
def delete_group(request, group_id):
    try:
        Group.objects.get(id=group_id).delete()
        return HttpResponse(status=204, headers={"HX-Trigger": "groupListReload"})
    except ProtectedError:
        error_message = (
            "Cannot delete group: it is in use by one or more relationships."
        )
        trigger = f'{{"showToast": {{"message": "{error_message}", "type": "error"}}}}'
        return HttpResponse(status=200, headers={"HX-Trigger": trigger})


@login_required
@require_http_methods(["POST"])
def update_group_order(request):
    """Update order for groups based on drag-and-drop reordering."""
    try:
        data = json.loads(request.body)
        group_ids = data.get("group_ids", [])

        if not group_ids:
            return JsonResponse(
                {"success": False, "error": "No group IDs provided"}, status=400
            )

        # Assign sequential order values
        for index, group_id in enumerate(group_ids):
            Group.objects.filter(id=group_id).update(order=index + 1)

        return JsonResponse({"success": True})

    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)
