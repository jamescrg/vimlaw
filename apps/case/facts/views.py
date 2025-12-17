from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.case.models import Document, Fact, Highlight
from apps.case.views import get_matter_from_url, get_session_key

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

    return {
        "facts": facts,
        "current_order": current_order,
        "keyword": keyword,
        "importances": list(range(1, 11)),
        "importance_value": importance_value,
        "selected_importance": (
            f"Importance {importance_value}" if importance_value else ""
        ),
    }


@login_required
def facts_index(request, matter_id):
    """Main facts view."""
    matter, matters = get_matter_from_url(request, matter_id)

    context = {
        "app": "documents",
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
        "app": "documents",
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
        "app": "documents",
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
        "app": "documents",
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
    fact.delete()

    return HttpResponse(status=204, headers={"HX-Trigger": "factsChanged"})


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
    }
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
    }
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
    }
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
