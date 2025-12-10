import json

from django.contrib.auth.decorators import login_required
from django.db.models import F, Max, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.case.documents.get_document_data import get_selected_matter
from apps.case.models import Document, Highlight

from .filters import OutlinesFilter
from .forms import OutlineForm
from .markdown_parser import export_outline_to_markdown, import_markdown_to_outline
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

    # Get category filter value
    category_key = filter_data.get("category", "")
    selected_category = ""
    if category_key:
        category_dict = dict(Outline.CATEGORY_CHOICES)
        selected_category = category_dict.get(category_key, "")

    return {
        "outlines": outlines,
        "current_order": current_order,
        "keyword": keyword,
        "importances": list(range(1, 11)),
        "importance_value": importance_value,
        "selected_category": selected_category,
        "selected_category_key": category_key,
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
def outlines_filter_category(request, category):
    """Filter outlines by category."""
    filter_data = request.session.get("outlines_filter", {})
    if category:
        filter_data["category"] = category
    else:
        filter_data.pop("category", None)

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
def outline_title(request, outline_id):
    """Update outline title inline."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        if title:
            outline.title = title
            outline.save()
        return HttpResponse(outline.title)
    # GET - return edit form
    return render(request, "outlines/title-edit.html", {"outline": outline})


@login_required
def outline_importance(request, outline_id, value):
    """Update outline importance."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)
    outline.importance = value
    outline.save()
    return HttpResponse(status=204, headers={"HX-Trigger": "outlinesChanged"})


@login_required
def outline_category(request, outline_id, value):
    """Update outline category."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)
    outline.category = value
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

    # Enforce rule: bullets after a heading must be children of that heading
    if parent is None:
        # Check for preceding heading at root level
        preceding_heading = (
            OutlineItem.objects.filter(
                outline=outline,
                parent__isnull=True,
                heading__isnull=False,
                order__lt=order,
            )
            .order_by("-order")
            .first()
        )

        if preceding_heading:
            # Make this item a child of the heading instead
            parent = preceding_heading
            # Recalculate order within heading's children
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

    # Return 204 for optimistic UI (client already updated DOM)
    return HttpResponse(status=204)


@login_required
def item_outdent(request, item_id):
    """Outdent item (move to parent's level)."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)

    if item.parent:
        grandparent = item.parent.parent
        parent_order = item.parent.order

        # Block outdent if it would create a top-level bullet after a heading
        if grandparent is None:
            preceding_heading = OutlineItem.objects.filter(
                outline=item.outline,
                parent__isnull=True,
                heading__isnull=False,
                order__lte=parent_order,
            ).exists()

            if preceding_heading:
                # Can't outdent - would violate the rule
                return HttpResponse(status=204)

        # Place after parent
        OutlineItem.objects.filter(
            outline=item.outline, parent=grandparent, order__gt=parent_order
        ).update(order=F("order") + 1)

        item.parent = grandparent
        item.order = parent_order + 1
        item.save()

    # Return 204 for optimistic UI (client already updated DOM)
    return HttpResponse(status=204)


@login_required
def item_toggle_collapse(request, item_id):
    """Toggle collapsed state."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)
    item.collapsed = not item.collapsed
    item.save()

    return render(request, "outlines/item.html", {"item": item})


@login_required
@require_POST
def expand_all(request, outline_id):
    """Expand all items in the outline."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)
    outline.items.filter(collapsed=True).update(collapsed=False)
    return HttpResponse(status=204, headers={"HX-Trigger": "outlineChanged"})


@login_required
@require_POST
def collapse_all(request, outline_id):
    """Collapse all items that have children."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)
    # Only collapse items that have children
    items_with_children = outline.items.filter(children__isnull=False).distinct()
    items_with_children.update(collapsed=True)
    return HttpResponse(status=204, headers={"HX-Trigger": "outlineChanged"})


@login_required
def item_toggle_heading(request, item_id):
    """Cycle heading level: None -> 2 -> 3 -> 4 -> 5 -> None."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)

    if item.heading is None:
        item.heading = 2
    elif item.heading >= 5:
        item.heading = None
    else:
        item.heading = item.heading + 1

    item.save()

    return render(request, "outlines/item.html", {"item": item})


@login_required
def item_set_heading(request, item_id, level):
    """Set heading level (0 for normal, 2-5 for headings).

    When promoting to heading: auto-adopt following root-level siblings.
    When demoting from heading: re-parent under preceding heading if one exists.
    """
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)

    old_heading = item.heading

    if level == 0:
        item.heading = None
    elif 2 <= level <= 5:
        item.heading = level

    item.save()

    # CASE A: Promoted to heading - adopt following root-level siblings
    if old_heading is None and item.heading is not None and item.parent is None:
        # Get root siblings that come after this item (until next heading)
        following_siblings = OutlineItem.objects.filter(
            outline=item.outline,
            parent__isnull=True,
            order__gt=item.order,
        ).order_by("order")

        # Find items until next heading
        items_to_adopt = []
        for sibling in following_siblings:
            if sibling.heading:
                break  # Stop at next heading
            items_to_adopt.append(sibling)

        if items_to_adopt:
            # Get starting order for children
            existing_children = item.get_children()
            next_order = (
                existing_children.last().order + 1 if existing_children.exists() else 0
            )

            # Adopt the siblings
            for sibling in items_to_adopt:
                sibling.parent = item
                sibling.order = next_order
                sibling.save()
                next_order += 1

    # CASE B: Demoted from heading - re-parent under preceding heading if exists
    elif old_heading is not None and item.heading is None and item.parent is None:
        # Find preceding heading
        preceding_heading = (
            OutlineItem.objects.filter(
                outline=item.outline,
                parent__isnull=True,
                heading__isnull=False,
                order__lt=item.order,
            )
            .order_by("-order")
            .first()
        )

        if preceding_heading:
            # Move this item under preceding heading (children stay attached)
            existing_children = preceding_heading.get_children()
            next_order = (
                existing_children.last().order + 1 if existing_children.exists() else 0
            )

            item.parent = preceding_heading
            item.order = next_order
            item.save()

    return render(request, "outlines/item.html", {"item": item})


@login_required
def item_toggle_highlight(request, item_id):
    """Toggle highlight state."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)
    item.highlight = not item.highlight
    item.save()

    return render(request, "outlines/item.html", {"item": item})


@login_required
def item_move_up(request, item_id):
    """Move item up among its siblings, or to parent's previous sibling if first child."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)
    prev_sibling = item.get_previous_sibling()

    if prev_sibling:
        # Swap order values with previous sibling
        item.order, prev_sibling.order = prev_sibling.order, item.order
        item.save()
        prev_sibling.save()
    elif item.parent:
        # First child - try to move to parent's previous sibling
        parent_prev_sibling = item.parent.get_previous_sibling()
        if parent_prev_sibling:
            # Get max order in new parent's children
            new_siblings = parent_prev_sibling.get_children()
            max_order = new_siblings.last().order + 1 if new_siblings.exists() else 0

            item.parent = parent_prev_sibling
            item.order = max_order
            item.save()

    return HttpResponse(status=204)


@login_required
def item_move_down(request, item_id):
    """Move item down among its siblings, or to parent's next sibling if last child."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)
    next_sibling = item.get_next_sibling()

    if next_sibling:
        # Swap order values with next sibling
        item.order, next_sibling.order = next_sibling.order, item.order
        item.save()
        next_sibling.save()
    elif item.parent:
        # Last child - try to move to parent's next sibling
        parent_next_sibling = item.parent.get_next_sibling()
        if parent_next_sibling:
            # Shift existing children down to make room at position 0
            parent_next_sibling.get_children().update(order=F("order") + 1)

            item.parent = parent_next_sibling
            item.order = 0
            item.save()

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

    # Block outdent if it would create top-level bullets after a heading
    if grandparent is None:
        preceding_heading = OutlineItem.objects.filter(
            outline=outline,
            parent__isnull=True,
            heading__isnull=False,
            order__lte=parent_order,
        ).exists()

        if preceding_heading:
            # Can't outdent - would violate the rule
            return HttpResponse(status=204)

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
    """Import markdown file into outline items."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)

    markdown_file = request.FILES.get("markdown_file")
    if not markdown_file:
        return HttpResponse("No file provided", status=400)

    # Read file content
    try:
        markdown_text = markdown_file.read().decode("utf-8")
    except UnicodeDecodeError:
        return HttpResponse("File must be UTF-8 encoded text", status=400)

    # Parse markdown and create items
    import_markdown_to_outline(outline, markdown_text)

    # Return 204 to close modal, trigger tree refresh
    return HttpResponse(status=204, headers={"HX-Trigger": "outlineChanged"})


@login_required
def export_markdown(request, outline_id):
    """Export outline as markdown file download."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)

    markdown_content = export_outline_to_markdown(outline)

    # Create response with markdown content as file download
    response = HttpResponse(markdown_content, content_type="text/markdown")
    # Sanitize filename
    safe_title = "".join(
        c for c in outline.title if c.isalnum() or c in (" ", "-", "_")
    ).strip()
    if not safe_title:
        safe_title = f"outline-{outline_id}"
    response["Content-Disposition"] = f'attachment; filename="{safe_title}.md"'

    return response


# =============================================================================
# Undo Operations
# =============================================================================


@login_required
@require_POST
def restore_items(request, outline_id):
    """Restore deleted items for undo functionality."""
    outline = get_object_or_404(Outline, id=outline_id, user=request.user)

    try:
        data = json.loads(request.body)
        items_data = data.get("items", [])
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    def create_item_recursive(item_data, parent=None):
        """Recursively create an item and its children."""
        # Get parent if parent_id specified
        if parent is None and item_data.get("parentId"):
            try:
                parent = OutlineItem.objects.get(
                    id=item_data["parentId"], outline=outline
                )
            except OutlineItem.DoesNotExist:
                parent = None

        item = OutlineItem.objects.create(
            outline=outline,
            parent=parent,
            content=item_data.get("content", ""),
            order=item_data.get("order", 0),
            collapsed=item_data.get("collapsed", False),
            heading=item_data.get("heading", False),
            highlight=item_data.get("highlight", False),
        )

        # Create children
        for child_data in item_data.get("children", []):
            create_item_recursive(child_data, parent=item)

        return item

    # Create all items
    for item_data in items_data:
        create_item_recursive(item_data)

    return HttpResponse(status=204)


@login_required
@require_POST
def item_restore_position(request, item_id):
    """Restore an item to a previous position for undo functionality."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)

    try:
        data = json.loads(request.body)
        parent_id = data.get("parent_id")
        order = data.get("order", 0)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    # Get new parent
    new_parent = None
    if parent_id:
        try:
            new_parent = OutlineItem.objects.get(id=parent_id, outline=item.outline)
        except OutlineItem.DoesNotExist:
            pass

    # Make room at the target position
    OutlineItem.objects.filter(
        outline=item.outline, parent=new_parent, order__gte=order
    ).exclude(id=item.id).update(order=F("order") + 1)

    item.parent = new_parent
    item.order = order
    item.save()

    return HttpResponse(status=204)


# =============================================================================
# Item Sources
# =============================================================================


@login_required
def item_sources_modal(request, item_id):
    """Render modal for managing item sources (documents and highlights)."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)
    return render(request, "outlines/sources-modal.html", {"item": item})


@login_required
def item_sources_search(request, item_id):
    """Search documents and highlights for item sources."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)
    matter = item.outline.matter
    query = request.GET.get("q", "").strip()

    documents = []
    highlights = []

    if query and matter:
        # Search documents by name
        documents = Document.objects.filter(matter=matter, name__icontains=query)[:10]

        # Search highlights by slug or text
        highlights = (
            Highlight.objects.filter(document__matter=matter)
            .filter(Q(slug__icontains=query) | Q(text__icontains=query))
            .select_related("document")[:10]
        )

    context = {
        "item": item,
        "documents": documents,
        "highlights": highlights,
        "query": query,
    }
    return render(request, "outlines/sources-results.html", context)


@login_required
@require_POST
def item_add_source(request, item_id):
    """Add a document or highlight as a source to an item."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)

    source_type = request.POST.get("type")
    source_id = request.POST.get("id")

    if source_type == "document":
        document = get_object_or_404(Document, pk=source_id)
        item.documents.add(document)
    elif source_type == "highlight":
        highlight = get_object_or_404(Highlight, pk=source_id)
        item.highlights.add(highlight)

    return render(request, "outlines/item.html", {"item": item})


@login_required
@require_POST
def item_remove_source(request, item_id):
    """Remove a document or highlight source from an item."""
    item = get_object_or_404(OutlineItem, id=item_id, outline__user=request.user)

    source_type = request.POST.get("type")
    source_id = request.POST.get("id")

    if source_type == "document":
        document = get_object_or_404(Document, pk=source_id)
        item.documents.remove(document)
    elif source_type == "highlight":
        highlight = get_object_or_404(Highlight, pk=source_id)
        item.highlights.remove(highlight)

    return render(request, "outlines/item.html", {"item": item})
