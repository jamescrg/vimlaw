import json

from django.contrib.auth.decorators import login_required
from django.db.models import F, Max
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.case.documents.get_document_data import get_selected_matter

from .forms import OutlineForm
from .models import Outline, OutlineItem

# =============================================================================
# Outline List Views
# =============================================================================


@login_required
def index(request):
    """Main outlines page."""
    matter, matters = get_selected_matter(request)
    outlines = Outline.objects.filter(user=request.user)

    context = {
        "app": "documents",
        "subapp": "outlines",
        "matter": matter,
        "matters": matters,
        "outlines": outlines,
    }
    return render(request, "outlines/main.html", context)


@login_required
def outlines_list(request):
    """HTMX partial for outline list."""
    outlines = Outline.objects.filter(user=request.user)

    return render(request, "outlines/list.html", {"outlines": outlines})


# =============================================================================
# Outline CRUD
# =============================================================================


@login_required
def outline_add(request):
    """Create a new outline."""
    matter, _ = get_selected_matter(request)

    if request.method == "POST":
        form = OutlineForm(request.POST)
        if form.is_valid():
            outline = form.save(commit=False)
            outline.user = request.user
            outline.matter = matter
            outline.save()
            # Create initial empty item
            OutlineItem.objects.create(outline=outline, content="", order=0)
            return HttpResponse(status=204, headers={"HX-Trigger": "outlinesChanged"})
    else:
        form = OutlineForm()

    return render(request, "outlines/form.html", {"form": form})


@login_required
def outline_edit(request, outline_id):
    """Edit outline metadata."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)

    if request.method == "POST":
        form = OutlineForm(request.POST, instance=outline)
        if form.is_valid():
            form.save()
            return HttpResponse(status=204, headers={"HX-Trigger": "outlinesChanged"})
    else:
        form = OutlineForm(instance=outline)

    return render(request, "outlines/form.html", {"form": form, "outline": outline})


@login_required
def outline_delete(request, outline_id):
    """Delete an outline."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)
    outline.delete()
    return HttpResponse(status=204, headers={"HX-Trigger": "outlinesChanged"})


# =============================================================================
# Outline View (Single Outline)
# =============================================================================


@login_required
def outline_view(request, outline_id):
    """View a single outline with its tree."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)
    root_items = outline.get_root_items()

    context = {
        "app": "outlines",
        "outline": outline,
        "root_items": root_items,
    }
    return render(request, "outlines/outline.html", context)


@login_required
def outline_standalone(request, outline_id):
    """View a single outline in standalone mode (no nav)."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)
    root_items = outline.get_root_items()

    context = {
        "outline": outline,
        "root_items": root_items,
    }
    return render(request, "outlines/outline-standalone.html", context)


@login_required
def outline_tree(request, outline_id):
    """HTMX partial for the outline tree."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)
    root_items = outline.get_root_items()

    return render(
        request,
        "outlines/tree.html",
        {"outline": outline, "root_items": root_items},
    )


# =============================================================================
# Item Operations
# =============================================================================


@login_required
def shortcuts_modal(request):
    """Show keyboard shortcuts modal."""
    return render(request, "outlines/shortcuts-modal.html")


@login_required
def item_content(request, item_id):
    """Get item content display (non-edit mode)."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)
    return render(request, "outlines/item-content.html", {"item": item})


@login_required
def item_edit(request, item_id):
    """Edit item content inline."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)

    if request.method == "POST":
        content = request.POST.get("content", "").strip()

        # Delete empty items
        if not content:
            prev_sibling = item.get_previous_sibling()
            prev_id = prev_sibling.id if prev_sibling else None
            item.delete()
            response = HttpResponse(status=200)
            response["HX-Reswap"] = "delete"
            response["HX-Retarget"] = "closest .outline-item"
            if prev_id:
                response["HX-Trigger"] = f'{{"itemDeleted": {{"focusId": {prev_id}}}}}'
            return response

        item.content = content
        item.save()
        return render(request, "outlines/item-content.html", {"item": item})

    # GET - return edit input
    return render(request, "outlines/item-edit.html", {"item": item})


@login_required
def item_create(request, outline_id):
    """Create a new item."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)

    parent_id = request.POST.get("parent_id")
    after_id = request.POST.get("after_id")

    parent = None
    if parent_id:
        parent = get_object_or_404(OutlineItem, id=parent_id, outline=outline)

    # Determine order
    if after_id:
        after_item = get_object_or_404(OutlineItem, id=after_id, outline=outline)
        order = after_item.order + 1
        # Shift subsequent siblings
        OutlineItem.objects.filter(
            outline=outline, parent=parent, order__gte=order
        ).update(order=F("order") + 1)
    else:
        # Add at end
        siblings = OutlineItem.objects.filter(outline=outline, parent=parent)
        max_order = siblings.aggregate(Max("order"))["order__max"] or -1
        order = max_order + 1

    item = OutlineItem.objects.create(
        outline=outline, parent=parent, content="", order=order
    )

    return render(request, "outlines/item.html", {"item": item, "editing": True})


@login_required
def item_delete(request, item_id):
    """Delete an item and its children."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)

    # Get previous item for focus
    prev_sibling = item.get_previous_sibling()
    prev_id = prev_sibling.id if prev_sibling else None

    item.delete()

    # Return empty response with focus hint
    response = HttpResponse(status=200)
    if prev_id:
        response["HX-Trigger"] = f'{{"itemDeleted": {{"focusId": {prev_id}}}}}'
    else:
        response["HX-Trigger"] = '{"itemDeleted": {}}'
    return response


@login_required
def item_indent(request, item_id):
    """Indent item (make child of previous sibling)."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)
    prev_sibling = item.get_previous_sibling()

    if prev_sibling:
        # Get max order among new siblings
        new_siblings = prev_sibling.get_children()
        max_order = 0
        if new_siblings.exists():
            max_order = new_siblings.last().order + 1

        item.parent = prev_sibling
        item.order = max_order
        item.save()

    return render(request, "outlines/item.html", {"item": item})


@login_required
def item_outdent(request, item_id):
    """Outdent item (move to parent's level)."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)

    if item.parent:
        grandparent = item.parent.parent
        parent_order = item.parent.order

        # Place after parent
        OutlineItem.objects.filter(
            outline=item.outline, parent=grandparent, order__gt=parent_order
        ).update(order=F("order") + 1)

        item.parent = grandparent
        item.order = parent_order + 1
        item.save()

    return render(request, "outlines/item.html", {"item": item})


@login_required
def item_toggle_collapse(request, item_id):
    """Toggle collapsed state."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)
    item.collapsed = not item.collapsed
    item.save()

    return render(request, "outlines/item.html", {"item": item})


@login_required
def item_move_up(request, item_id):
    """Move item up among its siblings."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)
    prev_sibling = item.get_previous_sibling()

    if prev_sibling:
        # Swap order values
        item.order, prev_sibling.order = prev_sibling.order, item.order
        item.save()
        prev_sibling.save()

    return HttpResponse(status=204)


@login_required
def item_move_down(request, item_id):
    """Move item down among its siblings."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)
    next_sibling = item.get_next_sibling()

    if next_sibling:
        # Swap order values
        item.order, next_sibling.order = next_sibling.order, item.order
        item.save()
        next_sibling.save()

    return HttpResponse(status=204)


@login_required
def item_move(request, item_id):
    """Move item to new position (for drag-drop)."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)

    new_parent_id = request.POST.get("parent_id")
    new_order = int(request.POST.get("order", 0))

    new_parent = None
    if new_parent_id:
        new_parent = get_object_or_404(
            OutlineItem, id=new_parent_id, outline=item.outline
        )

    # Update order of siblings at new position
    OutlineItem.objects.filter(
        outline=item.outline, parent=new_parent, order__gte=new_order
    ).exclude(id=item.id).update(order=F("order") + 1)

    item.parent = new_parent
    item.order = new_order
    item.save()

    return HttpResponse(status=204)


def filter_to_top_level_selected(items, item_ids_set):
    """Filter out items whose ancestor is also in the selection.

    If a parent and its descendants are all selected, only return the parent.
    """

    def has_selected_ancestor(item):
        """Check if any ancestor of this item is in the selection."""
        current = item.parent
        while current:
            if current.id in item_ids_set:
                return True
            current = current.parent
        return False

    return [item for item in items if not has_selected_ancestor(item)]


def get_visual_order(item):
    """Get a sortable key for visual order."""
    path = []
    current = item
    while current:
        path.insert(0, current.order)
        current = current.parent
    return path


@login_required
@require_POST
def batch_indent(request, outline_id):
    """Indent multiple items - make them children of the item above the first selected."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)

    try:
        data = json.loads(request.body)
        item_ids = data.get("item_ids", [])
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    if not item_ids:
        return HttpResponse(status=204)

    item_ids_set = set(item_ids)

    # Get all items
    items = list(
        OutlineItem.objects.filter(id__in=item_ids, outline=outline).order_by("id")
    )
    if not items:
        return HttpResponse(status=204)

    # Filter to only top-level selected items (exclude descendants of selected items)
    items = filter_to_top_level_selected(items, item_ids_set)
    if not items:
        return HttpResponse(status=204)

    # Sort by visual order
    items.sort(key=get_visual_order)
    first_item = items[0]

    # Find the new parent - the previous sibling of the first item
    new_parent = first_item.get_previous_sibling()
    if not new_parent:
        return HttpResponse(status=204)  # Can't indent if no previous sibling

    # Get starting order for new children
    existing_children = new_parent.get_children()
    next_order = 0
    if existing_children.exists():
        next_order = existing_children.last().order + 1

    # Move all top-level selected items to be children of new_parent
    for item in items:
        item.parent = new_parent
        item.order = next_order
        item.save()
        next_order += 1

    return HttpResponse(status=204)


@login_required
@require_POST
def batch_outdent(request, outline_id):
    """Outdent multiple items - move them to their parent's level."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)

    try:
        data = json.loads(request.body)
        item_ids = data.get("item_ids", [])
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    if not item_ids:
        return HttpResponse(status=204)

    item_ids_set = set(item_ids)

    # Get all items
    items = list(
        OutlineItem.objects.filter(id__in=item_ids, outline=outline).order_by("id")
    )
    if not items:
        return HttpResponse(status=204)

    # Filter to only top-level selected items (exclude descendants of selected items)
    items = filter_to_top_level_selected(items, item_ids_set)
    if not items:
        return HttpResponse(status=204)

    # Sort by visual order
    items.sort(key=get_visual_order)
    first_item = items[0]

    # Can only outdent if items have a parent
    if not first_item.parent:
        return HttpResponse(status=204)

    grandparent = first_item.parent.parent
    parent_order = first_item.parent.order

    # Make room after the parent
    OutlineItem.objects.filter(
        outline=outline, parent=grandparent, order__gt=parent_order
    ).update(order=F("order") + len(items))

    # Move all top-level selected items to grandparent level, after original parent
    next_order = parent_order + 1
    for item in items:
        item.parent = grandparent
        item.order = next_order
        item.save()
        next_order += 1

    return HttpResponse(status=204)
