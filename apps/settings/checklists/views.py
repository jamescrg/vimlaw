from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.management.selection import (
    all_visible_selected,
    clear_selected_ids,
    get_selected_ids,
    get_session_key,
    select_all_ids,
    selection_response,
    toggle_id,
)
from apps.settings.checklists.forms import (
    ChecklistFolderForm,
    ChecklistFolderMoveForm,
    ChecklistTemplateForm,
)
from apps.tasks.models import ChecklistFolder, ChecklistTemplate, ChecklistTemplateItem

CHECKLISTS_TRIGGER = "checklistsChanged"


# ---------------------------------------------------------------------------
# Tree-building utilities
# ---------------------------------------------------------------------------


def build_checklist_folder_tree_flat(folders_qs, expanded_ids):
    """Build a flat list of tree nodes from a queryset of folders."""
    folders = list(folders_qs.select_related("parent").order_by("name"))

    children_map = {}
    for f in folders:
        pid = f.parent_id
        children_map.setdefault(pid, []).append(f)

    result = []

    def _walk(parent_id, parent_visible):
        for f in children_map.get(parent_id, []):
            is_expanded = f.pk in expanded_ids
            has_children = f.pk in children_map
            is_visible = parent_visible
            result.append(
                {
                    "folder": f,
                    "level": f.depth,
                    "parent_id": f.parent_id,
                    "has_children": has_children,
                    "is_expanded": is_expanded,
                    "is_visible": is_visible,
                }
            )
            child_visible = is_visible and is_expanded
            _walk(f.pk, child_visible)

    _walk(None, True)
    return result


def get_valid_move_targets(exclude_folder):
    """Return folders excluding the given folder, its descendants, and depth-3 folders."""
    descendant_ids = [d.pk for d in exclude_folder.get_descendants()]
    exclude_ids = [exclude_folder.pk] + descendant_ids
    return (
        ChecklistFolder.objects.filter(depth__lt=3)
        .exclude(pk__in=exclude_ids)
        .order_by("name")
    )


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def get_checklist_folders_data(request):
    """Get checklist folders tree and selected folder from session."""
    folders = ChecklistFolder.objects.all()
    expanded_ids = set(request.session.get("checklist_folders_expanded", []))
    selected_folder_id = request.session.get("checklists_selected_folder_id")

    tree = build_checklist_folder_tree_flat(folders, expanded_ids)

    if selected_folder_id == "all":
        selected_folder = None
    elif selected_folder_id:
        try:
            selected_folder = ChecklistFolder.objects.get(pk=selected_folder_id)
        except ChecklistFolder.DoesNotExist:
            selected_folder = None
            request.session["checklists_selected_folder_id"] = None
    else:
        selected_folder = None

    return {
        "checklist_folder_tree": tree,
        "selected_checklist_folder": selected_folder,
        "all_folders_selected": selected_folder_id == "all",
    }


def get_checklists_data(request):
    """Get checklist templates data with filters applied from session."""
    filter_session_key = "settings_checklists_filter"
    filter_data = request.session.get(filter_session_key, {})

    queryset = ChecklistTemplate.objects.select_related("created_by").all()

    # Active/inactive filter
    status_filter = filter_data.get("status", "all")
    if status_filter == "active":
        queryset = queryset.filter(is_active=True)
    elif status_filter == "inactive":
        queryset = queryset.filter(is_active=False)

    # Folder filter
    selected_folder_id = request.session.get("checklists_selected_folder_id")
    if selected_folder_id == "all":
        pass
    elif selected_folder_id:
        queryset = queryset.filter(folder_id=selected_folder_id)
    else:
        queryset = queryset.filter(folder_id__isnull=True)

    # Keyword filter
    keyword = filter_data.get("keyword", "")
    if keyword:
        queryset = queryset.filter(name__icontains=keyword)

    # Sorting
    order_by = filter_data.get("order_by", "name")
    queryset = queryset.order_by(order_by)

    current_order = order_by.lstrip("-")

    templates_list = list(queryset)

    # Selection state
    session_key = get_session_key("selected_checklists")
    selected_checklists = get_selected_ids(request, session_key)
    visible_ids = [t.id for t in templates_list]

    return {
        "templates": templates_list,
        "current_order": current_order,
        "keyword": keyword,
        "status_filter": status_filter,
        "selected_checklists": selected_checklists,
        "all_selected": all_visible_selected(selected_checklists, visible_ids),
    }


# ---------------------------------------------------------------------------
# Page views
# ---------------------------------------------------------------------------


@login_required
def checklists_index(request):
    context = (
        {"subapp": "checklists"}
        | get_checklists_data(request)
        | get_checklist_folders_data(request)
    )
    return render(request, "settings/checklists/index.html", context)


@login_required
def checklists_list(request):
    context = get_checklists_data(request) | get_checklist_folders_data(request)
    return render(request, "settings/checklists/list.html", context)


@login_required
def checklists_table(request):
    context = get_checklists_data(request)
    return render(request, "settings/checklists/table.html", context)


# ---------------------------------------------------------------------------
# Sort and filter
# ---------------------------------------------------------------------------


@login_required
def checklists_order_by(request, order):
    filter_session_key = "settings_checklists_filter"
    filter_data = request.session.get(filter_session_key, {})

    current_order = filter_data.get("order_by", "")
    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session[filter_session_key] = filter_data
    request.session.modified = True

    return redirect("settings:checklists-list")


@login_required
def checklists_filter_keyword(request):
    filter_session_key = "settings_checklists_filter"
    filter_data = request.session.get(filter_session_key, {})
    keyword = request.GET.get("keyword", "").strip()

    if keyword:
        filter_data["keyword"] = keyword
    else:
        filter_data.pop("keyword", None)

    request.session[filter_session_key] = filter_data
    request.session.modified = True

    context = get_checklists_data(request)
    return render(request, "settings/checklists/table.html", context)


@login_required
def checklists_filter_status(request, status):
    filter_session_key = "settings_checklists_filter"
    filter_data = request.session.get(filter_session_key, {})
    filter_data["status"] = status
    request.session[filter_session_key] = filter_data
    request.session.modified = True

    return redirect("settings:checklists-list")


# ---------------------------------------------------------------------------
# Template CRUD
# ---------------------------------------------------------------------------


@login_required
def add_checklist_template(request):
    if request.method == "POST":
        form = ChecklistTemplateForm(request.POST)
        if form.is_valid():
            template = form.save(commit=False)
            # Place in currently selected folder
            selected_folder_id = request.session.get("checklists_selected_folder_id")
            if selected_folder_id and selected_folder_id != "all":
                try:
                    template.folder = ChecklistFolder.objects.get(pk=selected_folder_id)
                except ChecklistFolder.DoesNotExist:
                    pass
            template.save()
            return HttpResponse(status=204, headers={"HX-Trigger": CHECKLISTS_TRIGGER})
    else:
        form = ChecklistTemplateForm()

    return render(request, "settings/checklists/template-form.html", {"form": form})


@login_required
def edit_checklist_template(request, template_id):
    template = get_object_or_404(ChecklistTemplate, pk=template_id)

    if request.method == "POST":
        form = ChecklistTemplateForm(request.POST, instance=template)
        if form.is_valid():
            form.save()
            return HttpResponse(status=204, headers={"HX-Trigger": CHECKLISTS_TRIGGER})
    else:
        form = ChecklistTemplateForm(instance=template)

    items = template.items.all()
    context = {
        "form": form,
        "template": template,
        "items": items,
    }
    return render(request, "settings/checklists/template-form.html", context)


@login_required
@require_POST
def delete_checklist_template(request, template_id):
    get_object_or_404(ChecklistTemplate, pk=template_id).delete()
    return HttpResponse(status=204, headers={"HX-Trigger": CHECKLISTS_TRIGGER})


@login_required
def checklist_template_move(request, template_id):
    """Move a checklist template to a different folder via modal."""
    template = get_object_or_404(ChecklistTemplate, pk=template_id)
    all_folders = ChecklistFolder.objects.all()

    if request.method == "POST":
        folder_id = request.POST.get("destination")
        if folder_id:
            template.folder = get_object_or_404(ChecklistFolder, pk=folder_id)
        else:
            template.folder = None
        template.save(update_fields=["folder"])
        return HttpResponse(status=204, headers={"HX-Trigger": CHECKLISTS_TRIGGER})

    if template.folder:
        expanded_ids = set(a.pk for a in template.folder.get_ancestors())
    else:
        expanded_ids = set()
    tree = build_checklist_folder_tree_flat(all_folders, expanded_ids)

    context = {
        "template": template,
        "move_targets": tree,
    }
    return render(request, "settings/checklists/template-move.html", context)


# ---------------------------------------------------------------------------
# Template items
# ---------------------------------------------------------------------------


@login_required
def add_template_item(request, template_id):
    template = get_object_or_404(ChecklistTemplate, pk=template_id)

    if request.method == "POST":
        description = request.POST.get("description", "").strip()
        if description:
            max_order = (
                template.items.order_by("-order")
                .values_list("order", flat=True)
                .first()
                or 0
            )
            ChecklistTemplateItem.objects.create(
                template=template,
                description=description,
                order=max_order + 1,
            )

    items = template.items.all()
    return render(
        request,
        "settings/checklists/template-items.html",
        {"template": template, "items": items},
    )


@login_required
def delete_template_item(request, item_id):
    item = get_object_or_404(ChecklistTemplateItem, pk=item_id)
    template = item.template
    item.delete()

    items = template.items.all()
    return render(
        request,
        "settings/checklists/template-items.html",
        {"template": template, "items": items},
    )


# ---------------------------------------------------------------------------
# Folder views
# ---------------------------------------------------------------------------


@login_required
def checklist_folder_select(request, folder_id):
    saved = request.session.get("checklists_selected_folder_id")
    if folder_id == saved:
        request.session["checklists_selected_folder_id"] = None
    else:
        request.session["checklists_selected_folder_id"] = folder_id
    return redirect("settings:checklists-index")


@login_required
def checklist_folder_unsorted(request):
    request.session["checklists_selected_folder_id"] = None
    return redirect("settings:checklists-index")


@login_required
def checklist_folder_all(request):
    request.session["checklists_selected_folder_id"] = "all"
    return redirect("settings:checklists-index")


@login_required
def checklist_folder_add(request):
    if request.method == "POST":
        form = ChecklistFolderForm(request.POST)
        if form.is_valid():
            form.save()
            context = get_checklist_folders_data(request)
            response = render(request, "settings/checklists/folder-list.html", context)
            response.status_code = 202
            response["HX-Trigger-After-Swap"] = "closeModal"
            return response
    else:
        form = ChecklistFolderForm()
        selected_folder_id = request.session.get("checklists_selected_folder_id")
        if selected_folder_id and selected_folder_id != "all":
            try:
                selected = ChecklistFolder.objects.get(pk=selected_folder_id)
                if selected.can_have_children():
                    form.initial["parent"] = selected.pk
            except ChecklistFolder.DoesNotExist:
                pass

    context = {
        "form": form,
        "action": "/settings/checklists/folders/add/",
        "edit": False,
    }
    return render(request, "settings/checklists/folder-form.html", context)


@login_required
def checklist_folder_edit(request, folder_id):
    folder = get_object_or_404(ChecklistFolder, pk=folder_id)

    if request.method == "POST":
        form = ChecklistFolderForm(request.POST, instance=folder, exclude_folder=folder)
        if form.is_valid():
            old_parent_id = (
                ChecklistFolder.objects.filter(pk=folder.pk)
                .values_list("parent_id", flat=True)
                .first()
            )
            folder = form.save()
            if folder.parent_id != old_parent_id:
                folder.update_descendant_depths()
            context = get_checklist_folders_data(request)
            response = render(request, "settings/checklists/folder-list.html", context)
            response.status_code = 202
            response["HX-Trigger-After-Swap"] = "closeModal"
            return response
    else:
        form = ChecklistFolderForm(instance=folder, exclude_folder=folder)

    context = {
        "form": form,
        "action": f"/settings/checklists/folders/edit/{folder_id}",
        "edit": True,
        "folder": folder,
    }
    return render(request, "settings/checklists/folder-form.html", context)


@login_required
def checklist_folder_delete_confirm(request, folder_id):
    folder = get_object_or_404(ChecklistFolder, pk=folder_id)
    template_count = ChecklistTemplate.objects.filter(folder=folder).count()
    descendants = folder.get_descendants()
    subfolder_count = len(descendants)

    context = {
        "folder": folder,
        "template_count": template_count,
        "subfolder_count": subfolder_count,
    }
    return render(request, "settings/checklists/folder-delete-confirm.html", context)


@login_required
def checklist_folder_delete(request, folder_id):
    folder = get_object_or_404(ChecklistFolder, pk=folder_id)
    delete_templates = request.GET.get("delete_templates")
    delete_subfolders = request.GET.get("delete_subfolders")

    descendants = folder.get_descendants()
    parent_folder = folder.parent

    if delete_subfolders:
        for desc in reversed(descendants):
            ChecklistTemplate.objects.filter(folder=desc).update(folder=None)
            desc.delete()
        if delete_templates:
            ChecklistTemplate.objects.filter(folder=folder).delete()
    else:
        for child in folder.children.all():
            child.parent = parent_folder
            child.depth = parent_folder.depth + 1 if parent_folder else 0
            child.save(update_fields=["parent", "depth"])
            child.update_descendant_depths()

        if delete_templates:
            ChecklistTemplate.objects.filter(folder=folder).delete()

    if request.session.get("checklists_selected_folder_id") == folder_id:
        request.session["checklists_selected_folder_id"] = None

    folder.delete()

    return HttpResponse(status=204, headers={"HX-Refresh": "true"})


@login_required
def checklist_folder_move(request, folder_id):
    folder = get_object_or_404(ChecklistFolder, pk=folder_id)
    valid_targets = get_valid_move_targets(folder)

    if request.method == "POST":
        form = ChecklistFolderMoveForm(request.POST)
        form.fields["destination"].queryset = valid_targets
        if form.is_valid():
            destination = form.cleaned_data["destination"]
            folder.parent = destination
            folder.depth = destination.depth + 1 if destination else 0
            folder.save(update_fields=["parent", "depth"])
            folder.update_descendant_depths()

            context = get_checklist_folders_data(request)
            response = render(request, "settings/checklists/folder-list.html", context)
            response.status_code = 202
            response["HX-Trigger-After-Swap"] = "closeModal"
            return response

    expanded_ids = set(a.pk for a in folder.get_ancestors()) if folder.parent else set()
    tree = build_checklist_folder_tree_flat(valid_targets, expanded_ids)

    context = {
        "folder": folder,
        "move_targets": tree,
    }
    return render(request, "settings/checklists/folder-move.html", context)


@login_required
@require_POST
def checklist_folder_toggle_expand(request, folder_id):
    expanded = request.session.get("checklist_folders_expanded", [])
    if folder_id in expanded:
        expanded.remove(folder_id)
    else:
        expanded.append(folder_id)
    request.session["checklist_folders_expanded"] = expanded
    request.session.modified = True
    return HttpResponse(status=204)


@login_required
@require_POST
def checklist_folder_toggle_all(request):
    expand = request.GET.get("expand") == "true"
    if expand:
        all_ids = list(ChecklistFolder.objects.values_list("pk", flat=True))
        request.session["checklist_folders_expanded"] = all_ids
    else:
        request.session["checklist_folders_expanded"] = []
    request.session.modified = True
    return HttpResponse(status=204)


# ---------------------------------------------------------------------------
# Multi-select views
# ---------------------------------------------------------------------------


@login_required
@require_POST
def checklists_toggle_select(request, template_id):
    get_object_or_404(ChecklistTemplate, pk=template_id)
    toggle_id(request, get_session_key("selected_checklists"), template_id)
    return selection_response(CHECKLISTS_TRIGGER)


@login_required
@require_POST
def checklists_select_all(request):
    visible_ids = [t.id for t in get_checklists_data(request)["templates"]]
    select_all_ids(request, get_session_key("selected_checklists"), visible_ids)
    return selection_response(CHECKLISTS_TRIGGER)


@login_required
@require_POST
def checklists_clear_selection(request):
    clear_selected_ids(request, get_session_key("selected_checklists"))
    return selection_response(CHECKLISTS_TRIGGER)


@login_required
def checklists_bulk_move(request):
    key = get_session_key("selected_checklists")
    selected = get_selected_ids(request, key)
    if not selected:
        return HttpResponse(status=400, content="No checklists selected.")

    if request.method == "POST":
        folder_id = request.POST.get("destination")
        if folder_id:
            folder = get_object_or_404(ChecklistFolder, pk=folder_id)
        else:
            folder = None
        ChecklistTemplate.objects.filter(id__in=selected).update(folder=folder)
        clear_selected_ids(request, key)
        return HttpResponse(status=204, headers={"HX-Trigger": CHECKLISTS_TRIGGER})

    all_folders = ChecklistFolder.objects.all()
    tree = build_checklist_folder_tree_flat(all_folders, set())

    context = {
        "selected_count": len(selected),
        "move_targets": tree,
    }
    return render(request, "settings/checklists/bulk-move.html", context)


@login_required
@require_POST
def checklists_bulk_delete(request):
    key = get_session_key("selected_checklists")
    selected = get_selected_ids(request, key)
    if not selected:
        return HttpResponse(status=400, content="No checklists selected.")

    ChecklistTemplate.objects.filter(id__in=selected).delete()
    clear_selected_ids(request, key)

    return selection_response(CHECKLISTS_TRIGGER)
