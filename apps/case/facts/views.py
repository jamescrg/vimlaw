from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.case.models import Document, Fact, Highlight, Label
from apps.case.views import get_matter_from_url, get_session_key, set_last_tab
from apps.management.selection import (
    all_visible_selected,
    clear_selected_ids,
    get_selected_ids,
    select_all_ids,
    selection_response,
    toggle_id,
)

from .filters import FactsFilter
from .forms import FactForm
from .generate_pdf import generate_facts_pdf


def get_facts_data(request, matter, matter_id):
    """Get facts data with filters applied from session."""
    filter_session_key = get_session_key("facts_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    facts = []
    if matter:
        queryset = Fact.objects.filter(matter=matter).order_by("date", "time")

        # Apply filters if present
        if filter_data:
            facts_filter = FactsFilter(filter_data, queryset=queryset)
            facts = facts_filter.qs
        else:
            facts = queryset

    # Get current sort order
    current_order = filter_data.get("order_by", "date")
    if isinstance(current_order, list):
        current_order = current_order[0] if current_order else "date"

    # Get keyword value
    keyword = filter_data.get("keyword", "")
    if isinstance(keyword, list):
        keyword = keyword[0] if keyword else ""

    # Get importance filter value
    importance_value = filter_data.get("importance")
    importance_value = (
        int(importance_value) if importance_value not in (None, "", 0) else None
    )

    selected_key = get_session_key("selected_facts", matter_id)
    selected_facts = get_selected_ids(request, selected_key)
    visible_ids = [fact.id for fact in facts]
    all_selected = all_visible_selected(selected_facts, visible_ids)

    return {
        "facts": facts,
        "selected_facts": selected_facts,
        "all_selected": all_selected,
        "fact_colors": [value for value, _ in Fact.COLOR_CHOICES if value],
        "current_order": current_order,
        "keyword": keyword,
        "importances": list(range(7, 0, -1)),
        "importance_value": importance_value,
        "selected_importance": (
            {
                7: "Highest",
                6: "Higher",
                5: "High",
                4: "Normal",
                3: "Low",
                2: "Lower",
                1: "Lowest",
            }.get(importance_value, "")
            if importance_value
            else ""
        ),
    }


@login_required
def facts_index(request, matter_id):
    """Main facts view."""
    matter, matters = get_matter_from_url(request, matter_id)
    set_last_tab(request, matter_id, "facts")

    context = {
        "app": "matters",
        "subapp": "facts",
        "matter": matter,
        "matters": matters,
    } | get_facts_data(request, matter, matter_id)

    return render(request, "case/facts/main.html", context)


@login_required
def facts_list(request, matter_id):
    """HTMX partial for facts list."""
    matter, matters = get_matter_from_url(request, matter_id)

    context = {
        "app": "matters",
        "subapp": "facts",
        "matter": matter,
        "matters": matters,
    } | get_facts_data(request, matter, matter_id)

    return render(request, "case/facts/list.html", context)


@login_required
def facts_add(request, matter_id):
    """Add a new fact."""
    matter, matters = get_matter_from_url(request, matter_id)

    if request.method == "POST":
        form = FactForm(request.POST, use_required_attribute=False)
        if form.is_valid():
            fact = form.save(commit=False)
            fact.user = request.user
            fact.matter = matter
            fact.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "factsChanged"})
    else:
        form = FactForm(use_required_attribute=False)

    context = {
        "app": "matters",
        "subapp": "facts",
        "matter": matter,
        "form": form,
        "action": "Add",
    }

    return render(request, "case/facts/form.html", context)


@login_required
def facts_edit(request, fact_id):
    """Edit a fact."""
    fact = get_object_or_404(Fact, pk=fact_id)
    matter = fact.matter

    if request.method == "POST":
        form = FactForm(request.POST, instance=fact, use_required_attribute=False)
        if form.is_valid():
            fact = form.save(commit=False)
            fact.user = request.user
            fact.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "factsChanged"})
    else:
        form = FactForm(instance=fact, use_required_attribute=False)

    context = {
        "app": "matters",
        "subapp": "facts",
        "matter": matter,
        "fact": fact,
        "form": form,
        "action": "Edit",
    }

    return render(request, "case/facts/form.html", context)


@login_required
@require_POST
def facts_delete(request, fact_id):
    """Delete a fact."""
    fact = get_object_or_404(Fact, pk=fact_id)

    # Prune the id from any current selection so the bulk count stays honest.
    key = get_session_key("selected_facts", fact.matter_id)
    selected = get_selected_ids(request, key)
    if fact.id in selected:
        selected.remove(fact.id)
        request.session[key] = selected

    fact.delete()

    return HttpResponse(status=204, headers={"HX-Trigger": "factsChanged"})


# ── Selection & bulk actions ─────────────────────────────────────────────────


def _selected_facts_qs(matter, selected):
    return Fact.objects.filter(matter=matter, id__in=selected)


def _fact_selection_context(request, fact):
    """Selection state for standalone fact-row renders, so a row swap
    doesn't lose its checkbox state."""
    key = get_session_key("selected_facts", fact.matter_id)
    return {"selected_facts": get_selected_ids(request, key)}


@login_required
@require_POST
def toggle_fact_select(request, matter_id, fact_id):
    """Toggle selection of a single fact."""
    get_object_or_404(Fact, id=fact_id, matter_id=matter_id)
    key = get_session_key("selected_facts", matter_id)
    toggle_id(request, key, fact_id)
    return selection_response("factsChanged")


@login_required
@require_POST
def select_all_facts(request, matter_id):
    """Select all visible (filtered) facts, or deselect if all selected."""
    matter, _ = get_matter_from_url(request, matter_id)
    key = get_session_key("selected_facts", matter_id)
    visible_ids = [
        fact.id for fact in get_facts_data(request, matter, matter_id)["facts"]
    ]
    select_all_ids(request, key, visible_ids)
    return selection_response("factsChanged")


@login_required
@require_POST
def clear_fact_selection(request, matter_id):
    """Clear the fact selection."""
    clear_selected_ids(request, get_session_key("selected_facts", matter_id))
    return selection_response("factsChanged")


@login_required
@require_POST
def bulk_facts_delete(request, matter_id):
    """Delete all selected facts."""
    matter, _ = get_matter_from_url(request, matter_id)
    key = get_session_key("selected_facts", matter_id)
    selected = get_selected_ids(request, key)

    if not selected:
        return HttpResponse(status=400, content="No facts selected.")

    _selected_facts_qs(matter, selected).delete()
    clear_selected_ids(request, key)

    return selection_response("factsChanged")


@login_required
@require_POST
def bulk_facts_importance(request, matter_id):
    """Bulk set importance on selected facts."""
    matter, _ = get_matter_from_url(request, matter_id)
    key = get_session_key("selected_facts", matter_id)
    selected = get_selected_ids(request, key)

    if not selected:
        return HttpResponse(status=400, content="No facts selected.")

    importance = request.POST.get("importance")
    if importance:
        _selected_facts_qs(matter, selected).update(importance=int(importance))

    clear_selected_ids(request, key)
    return selection_response("factsChanged")


@login_required
@require_POST
def bulk_facts_color(request, matter_id):
    """Bulk set (or clear) the row color on selected facts."""
    matter, _ = get_matter_from_url(request, matter_id)
    key = get_session_key("selected_facts", matter_id)
    selected = get_selected_ids(request, key)

    if not selected:
        return HttpResponse(status=400, content="No facts selected.")

    color = request.POST.get("color", "")
    valid_colors = {value for value, _ in Fact.COLOR_CHOICES if value}
    if color and color not in valid_colors:
        return HttpResponse(status=400, content="Invalid color.")

    _selected_facts_qs(matter, selected).update(color=color or None)

    clear_selected_ids(request, key)
    return selection_response("factsChanged")


def _render_bulk_labels_modal(request, matter, matter_id, extra_headers=None):
    """Render the bulk-labels modal for the facts currently selected."""
    key = get_session_key("selected_facts", matter_id)
    selected = get_selected_ids(request, key)

    if not selected:
        return HttpResponse(status=400, content="No facts selected.")

    labels = Label.objects.filter(Q(matter=None) | Q(matter=matter)).order_by(
        "matter", "name"
    )
    facts = _selected_facts_qs(matter, selected)
    selected_count = facts.count()

    applied_labels = []
    available_labels = []
    for label in labels:
        with_label = facts.filter(labels=label).count()
        if with_label == 0:
            state = "none"
        elif with_label == selected_count:
            state = "all"
        else:
            state = "some"
        item = {
            "id": label.id,
            "name": label.name,
            "color": label.color,
            "state": state,
        }
        if state == "all":
            applied_labels.append(item)
        else:
            available_labels.append(item)

    response = render(
        request,
        "case/facts/bulk_labels_modal.html",
        {
            "matter": matter,
            "applied_labels": applied_labels,
            "available_labels": available_labels,
            "has_labels": labels.exists(),
            "selected_count": selected_count,
        },
    )
    if extra_headers:
        for header, value in extra_headers.items():
            response[header] = value
    return response


@login_required
def bulk_facts_labels_modal(request, matter_id):
    """Open the bulk-labels modal."""
    matter, _ = get_matter_from_url(request, matter_id)
    return _render_bulk_labels_modal(request, matter, matter_id)


@login_required
@require_POST
def bulk_facts_label_action(request, matter_id):
    """Add or remove a single label from all selected facts."""
    matter, _ = get_matter_from_url(request, matter_id)
    key = get_session_key("selected_facts", matter_id)
    selected = get_selected_ids(request, key)

    if not selected:
        return HttpResponse(status=400, content="No facts selected.")

    label = get_object_or_404(Label, id=request.POST.get("label_id"))
    action = request.POST.get("action")
    facts = _selected_facts_qs(matter, selected)

    if action == "add":
        for fact in facts:
            fact.labels.add(label)
    elif action == "remove":
        for fact in facts:
            fact.labels.remove(label)
    else:
        return HttpResponse(status=400, content="Invalid action.")

    return _render_bulk_labels_modal(
        request, matter, matter_id, extra_headers={"HX-Trigger": "factsChanged"}
    )


@login_required
def facts_print(request, matter_id):
    """Print view for facts."""
    matter, matters = get_matter_from_url(request, matter_id)

    facts = []
    if matter:
        facts = Fact.objects.filter(matter=matter).order_by("date", "time")

    context = {
        "matter": matter,
        "facts": facts,
    }
    return render(request, "case/facts/print.html", context)


@login_required
def facts_pdf(request, matter_id):
    """Generate PDF for facts."""
    import os
    from datetime import datetime

    matter, matters = get_matter_from_url(request, matter_id)

    file = generate_facts_pdf(matter.id, request)

    current_date = datetime.now().strftime("%Y-%m-%d")

    with open(file.name, "rb") as pdf:
        response = HttpResponse(pdf.read(), content_type="application/pdf")
        filename = f'filename="Facts - {matter.name} - {current_date}.pdf"'
        response["Content-Disposition"] = f"attachment; {filename}"

    os.unlink(file.name)

    return response


@login_required
def facts_edit_description(request, fact_id):
    """Inline edit fact description."""
    fact = get_object_or_404(Fact, pk=fact_id)
    matter = fact.matter
    context = {"fact": fact, "matter": matter}
    return render(request, "case/facts/edit-description.html", context)


@login_required
def facts_update_description(request, fact_id):
    """Update fact description inline."""
    fact = get_object_or_404(Fact, pk=fact_id)
    fact.description = request.POST.get("description")
    fact.save()

    context = {
        "matter": fact.matter,
        "fact": fact,
    } | _fact_selection_context(request, fact)
    return render(request, "case/facts/fact-row.html", context)


@login_required
def fact_sources_modal(request, fact_id):
    """Render modal for managing fact sources (documents and highlights)."""
    fact = get_object_or_404(Fact, pk=fact_id)
    matter = fact.matter
    context = {
        "fact": fact,
        "matter": matter,
    }
    return render(request, "case/facts/sources-modal.html", context)


@login_required
def fact_sources_search(request, fact_id):
    """Search documents and highlights for fact sources."""
    from django.db.models import Q

    fact = get_object_or_404(Fact, pk=fact_id)
    matter = fact.matter
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
        "fact": fact,
        "documents": documents,
        "highlights": highlights,
        "query": query,
    }
    return render(request, "case/facts/sources-results.html", context)


@login_required
@require_POST
def fact_add_source(request, fact_id):
    """Add a document or highlight as a source to a fact."""
    fact = get_object_or_404(Fact, pk=fact_id)
    matter = fact.matter

    source_type = request.POST.get("type")
    source_id = request.POST.get("id")

    if source_type == "document":
        document = get_object_or_404(Document, pk=source_id)
        fact.documents.add(document)
    elif source_type == "highlight":
        highlight = get_object_or_404(Highlight, pk=source_id)
        fact.highlights.add(highlight)

    context = {
        "matter": matter,
        "fact": fact,
    } | _fact_selection_context(request, fact)
    return render(request, "case/facts/fact-row.html", context)


@login_required
@require_POST
def fact_remove_source(request, fact_id):
    """Remove a document or highlight source from a fact."""
    fact = get_object_or_404(Fact, pk=fact_id)
    matter = fact.matter

    source_type = request.POST.get("type")
    source_id = request.POST.get("id")

    if source_type == "document":
        document = get_object_or_404(Document, pk=source_id)
        fact.documents.remove(document)
    elif source_type == "highlight":
        highlight = get_object_or_404(Highlight, pk=source_id)
        fact.highlights.remove(highlight)

    context = {
        "matter": matter,
        "fact": fact,
    } | _fact_selection_context(request, fact)
    return render(request, "case/facts/fact-row.html", context)


@login_required
def fact_importance(request, fact_id, importance):
    """Set fact importance."""
    fact = get_object_or_404(Fact, pk=fact_id)
    fact.importance = importance
    fact.save()
    return redirect("case:facts-list", matter_id=fact.matter_id)


@login_required
def facts_filter(request, matter_id):
    """Filter modal for facts - GET shows modal, POST saves to session."""
    matter, matters = get_matter_from_url(request, matter_id)
    filter_session_key = get_session_key("facts_filter", matter_id)

    if request.method == "POST":
        filter_data = {
            key: value
            for key, value in request.POST.items()
            if key != "csrfmiddlewaretoken"
        }
        request.session[filter_session_key] = filter_data
        request.session.modified = True
        return HttpResponse(status=204, headers={"HX-Trigger": "factsChanged"})

    # GET - show filter modal
    filter_data = request.session.get(filter_session_key, {})

    queryset = Fact.objects.filter(matter=matter) if matter else Fact.objects.none()

    filter_obj = FactsFilter(filter_data, queryset=queryset)

    return render(
        request, "case/facts/filter.html", {"filter": filter_obj, "matter": matter}
    )


@login_required
def facts_sort(request, matter_id, order):
    """Sort facts by field, toggling asc/desc."""
    filter_session_key = get_session_key("facts_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session[filter_session_key] = filter_data
    request.session.modified = True

    return redirect("case:facts-list", matter_id=matter_id)


@login_required
def facts_filter_keyword(request, matter_id):
    """Filter facts by keyword (inline search)."""
    matter, _ = get_matter_from_url(request, matter_id)
    filter_session_key = get_session_key("facts_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    keyword = request.GET.get("keyword", "").strip()

    if keyword:
        filter_data["keyword"] = keyword
    else:
        filter_data.pop("keyword", None)

    request.session[filter_session_key] = filter_data

    # Render just the table partial (for search input updates)
    context = {"matter": matter} | get_facts_data(request, matter, matter_id)
    return render(request, "case/facts/table.html", context)


@login_required
def facts_filter_importance(request, matter_id, importance_value):
    """Filter facts by importance level."""
    filter_session_key = get_session_key("facts_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    # Set to empty string when 0 (All) is selected, otherwise use the value
    filter_data["importance"] = "" if importance_value == 0 else importance_value

    request.session[filter_session_key] = filter_data

    return redirect("case:facts-list", matter_id=matter_id)
