import json

from django.contrib.auth.decorators import login_required
from django.db.models import F, Max
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.case.documents.get_document_data import get_selected_matter

from .filters import OutlinesFilter
from .forms import OutlineForm
from .markdown_parser import import_markdown_to_outline
from .models import Outline, OutlineItem


def get_outlines_data(request, matter):
    """Get outlines data with filters applied from session."""
    filter_data = request.session.get("outlines_filter", {})

    outlines = []
    if matter:
        queryset = Outline.objects.filter(matter=matter)

        # Apply filters if present
        if filter_data:
            outlines_filter = OutlinesFilter(
                filter_data, queryset=queryset, matter=matter
            )
            outlines = outlines_filter.qs
        else:
            outlines = queryset

        # Apply sorting
        current_order = filter_data.get("order_by", "-date")
        if current_order:
            outlines = outlines.order_by(current_order)
        else:
            outlines = outlines.order_by("-date")

    # Get current sort order for template
    current_order = filter_data.get("order_by", "-date")

    # Get keyword value
    keyword = filter_data.get("keyword", "")

    # Get importance filter value
    importance_value = filter_data.get("importance")
    importance_value = (
        int(importance_value) if importance_value not in (None, "", 0) else None
    )

    return {
        "outlines": outlines,
        "current_order": current_order,
        "keyword": keyword,
        "importances": list(range(1, 11)),
        "importance_value": importance_value,
    }


# =============================================================================
# Outline List Views
# =============================================================================


@login_required
def index(request):
    """Main outlines page."""
    matter, matters = get_selected_matter(request)

    context = {
        "app": "documents",
        "subapp": "outlines",
        "matter": matter,
        "matters": matters,
    } | get_outlines_data(request, matter)

    return render(request, "outlines/main.html", context)


@login_required
def outlines_list(request):
    """HTMX partial for outline list."""
    matter, _ = get_selected_matter(request)

    return render(request, "outlines/list.html", get_outlines_data(request, matter))


@login_required
def outlines_filter(request):
    """Filter modal for outlines - GET shows modal, POST saves to session."""
    matter, _ = get_selected_matter(request)

    if request.method == "POST":
        filter_data = {
            key: value
            for key, value in request.POST.items()
            if key != "csrfmiddlewaretoken"
        }
        request.session["outlines_filter"] = filter_data
        request.session.modified = True
        return HttpResponse(status=204, headers={"HX-Trigger": "outlinesChanged"})

    # GET - show filter modal
    filter_data = request.session.get("outlines_filter", {})

    queryset = (
        Outline.objects.filter(matter=matter) if matter else Outline.objects.none()
    )

    filter_obj = OutlinesFilter(filter_data, queryset=queryset, matter=matter)

    return render(request, "outlines/filter.html", {"filter": filter_obj})


@login_required
def outlines_sort(request, order):
    """Sort outlines by field, toggling asc/desc."""
    filter_data = request.session.get("outlines_filter", {})

    current_order = filter_data.get("order_by", "")

    # Toggle between asc and desc
    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    elif current_order == f"-{order}":
        new_order = order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session["outlines_filter"] = filter_data
    request.session.modified = True

    return redirect("outlines:list")


@login_required
def outlines_filter_importance(request, importance_value):
    """Filter outlines by importance level."""
    filter_data = request.session.get("outlines_filter", {})
    # Set to empty string when 0 (All) is selected, otherwise use the value
    filter_data["importance"] = "" if importance_value == 0 else importance_value

    request.session["outlines_filter"] = filter_data

    return redirect("outlines:list")


@login_required
def outlines_filter_keyword(request):
    """Filter outlines by keyword (inline search)."""
    matter, _ = get_selected_matter(request)
    filter_data = request.session.get("outlines_filter", {})
    keyword = request.GET.get("keyword", "").strip()

    if keyword:
        filter_data["keyword"] = keyword
    else:
        filter_data.pop("keyword", None)

    request.session["outlines_filter"] = filter_data

    # Render just the table partial (for search input updates)
    context = get_outlines_data(request, matter)
    return render(request, "outlines/table.html", context)


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


@login_required
def outline_importance(request, outline_id, value):
    """Update outline importance."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)
    outline.importance = value
    outline.save()
    return HttpResponse(status=204, headers={"HX-Trigger": "outlinesChanged"})


# =============================================================================
# Outline View (Single Outline)
# =============================================================================


@login_required
def outline_standalone(request, outline_id):
    """View a single outline in standalone mode (no nav)."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)

    # Update viewed_at timestamp
    outline.viewed_at = timezone.now()
    outline.save(update_fields=["viewed_at"])

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
            item_id = item.id
            item.delete()
            response = HttpResponse(status=200)
            # Trigger JS to remove the item from DOM
            trigger_data = {"itemId": item_id}
            if prev_id:
                trigger_data["focusId"] = prev_id
            response["HX-Trigger"] = json.dumps({"itemDeleted": trigger_data})
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
def item_toggle_heading(request, item_id):
    """Toggle heading state."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)
    item.heading = not item.heading
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


# =============================================================================
# Import from Markdown
# =============================================================================


@login_required
def import_modal(request, outline_id):
    """Show the import from markdown modal."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)
    return render(request, "outlines/import-modal.html", {"outline": outline})


@login_required
@require_POST
def import_markdown(request, outline_id):
    """Import markdown list into outline items."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)
    markdown_text = request.POST.get("markdown", "")

    # Parse markdown and create items
    import_markdown_to_outline(outline, markdown_text)

    # Return 204 to close modal, trigger tree refresh
    return HttpResponse(status=204, headers={"HX-Trigger": "outlineChanged"})
