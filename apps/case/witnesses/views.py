from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from apps.case.models import Highlight, Witness
from apps.case.views import get_matter_from_url, get_session_key, set_last_tab
from apps.management.selection import (
    all_visible_selected,
    clear_selected_ids,
    get_selected_ids,
    select_all_ids,
    selection_response,
    toggle_id,
)

from .filters import WitnessesFilter
from .forms import WitnessForm


def get_witnesses_data(request, matter, matter_id):
    """Get witnesses data with filters applied from session."""
    filter_session_key = get_session_key("witnesses_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    witnesses = []
    if matter:
        queryset = Witness.objects.filter(matter=matter).order_by("name")

        # Apply filters if present
        if filter_data:
            witnesses_filter = WitnessesFilter(filter_data, queryset=queryset)
            witnesses = witnesses_filter.qs
        else:
            witnesses = queryset

    # Get current sort order
    current_order = filter_data.get("order_by", "name")
    if isinstance(current_order, list):
        current_order = current_order[0] if current_order else "name"

    # Get keyword value
    keyword = filter_data.get("keyword", "")
    if isinstance(keyword, list):
        keyword = keyword[0] if keyword else ""

    # Get importance filter value
    importance_value = filter_data.get("importance")
    importance_value = (
        int(importance_value) if importance_value not in (None, "", 0) else None
    )

    selected_key = get_session_key("selected_witnesses", matter_id)
    selected_witnesses = get_selected_ids(request, selected_key)
    visible_ids = [witness.id for witness in witnesses]
    all_selected = all_visible_selected(selected_witnesses, visible_ids)

    return {
        "witnesses": witnesses,
        "selected_witnesses": selected_witnesses,
        "all_selected": all_selected,
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
def witnesses_index(request, matter_id):
    """Main witnesses view."""
    matter, matters = get_matter_from_url(request, matter_id)
    set_last_tab(request, matter_id, "witnesses")

    context = {
        "app": "matters",
        "subapp": "witnesses",
        "matter": matter,
        "matters": matters,
    } | get_witnesses_data(request, matter, matter_id)

    return render(request, "case/witnesses/main.html", context)


@login_required
def witnesses_list(request, matter_id):
    """HTMX partial for witnesses list."""
    matter, matters = get_matter_from_url(request, matter_id)

    context = {
        "app": "matters",
        "subapp": "witnesses",
        "matter": matter,
        "matters": matters,
    } | get_witnesses_data(request, matter, matter_id)

    return render(request, "case/witnesses/list.html", context)


@login_required
def witnesses_add(request, matter_id):
    """Add a new witness."""
    matter, matters = get_matter_from_url(request, matter_id)

    if request.method == "POST":
        form = WitnessForm(request.POST, use_required_attribute=False)
        if form.is_valid():
            witness = form.save(commit=False)
            witness.user = request.user
            witness.matter = matter
            witness.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "witnessesChanged"})
    else:
        form = WitnessForm(use_required_attribute=False)

    context = {
        "app": "matters",
        "subapp": "witnesses",
        "matter": matter,
        "form": form,
        "action": "Add",
    }

    return render(request, "case/witnesses/form.html", context)


@login_required
def witnesses_edit(request, witness_id):
    """Edit a witness."""
    witness = get_object_or_404(Witness, pk=witness_id)
    matter = witness.matter

    if request.method == "POST":
        form = WitnessForm(request.POST, instance=witness, use_required_attribute=False)
        if form.is_valid():
            witness = form.save(commit=False)
            witness.user = request.user
            witness.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "witnessesChanged"})
    else:
        form = WitnessForm(instance=witness, use_required_attribute=False)

    context = {
        "app": "matters",
        "subapp": "witnesses",
        "matter": matter,
        "witness": witness,
        "form": form,
        "action": "Edit",
    }

    return render(request, "case/witnesses/form.html", context)


@login_required
@require_POST
def witnesses_delete(request, witness_id):
    """Delete a witness."""
    witness = get_object_or_404(Witness, pk=witness_id)

    # Prune the id from any current selection so the bulk count stays honest.
    key = get_session_key("selected_witnesses", witness.matter_id)
    selected = get_selected_ids(request, key)
    if witness.id in selected:
        selected.remove(witness.id)
        request.session[key] = selected

    witness.delete()

    return HttpResponse(status=204, headers={"HX-Trigger": "witnessesChanged"})


# ── Selection & bulk actions ─────────────────────────────────────────────────


def _selected_witnesses_qs(matter, selected):
    return Witness.objects.filter(matter=matter, id__in=selected)


@login_required
@require_POST
def toggle_witness_select(request, matter_id, witness_id):
    """Toggle selection of a single witness."""
    get_object_or_404(Witness, id=witness_id, matter_id=matter_id)
    key = get_session_key("selected_witnesses", matter_id)
    toggle_id(request, key, witness_id)
    return selection_response("witnessesChanged")


@login_required
@require_POST
def select_all_witnesses(request, matter_id):
    """Select all visible (filtered) witnesses, or deselect if all selected."""
    matter, _ = get_matter_from_url(request, matter_id)
    key = get_session_key("selected_witnesses", matter_id)
    visible_ids = [
        witness.id
        for witness in get_witnesses_data(request, matter, matter_id)["witnesses"]
    ]
    select_all_ids(request, key, visible_ids)
    return selection_response("witnessesChanged")


@login_required
@require_POST
def clear_witness_selection(request, matter_id):
    """Clear the witness selection."""
    clear_selected_ids(request, get_session_key("selected_witnesses", matter_id))
    return selection_response("witnessesChanged")


@login_required
@require_POST
def bulk_witnesses_delete(request, matter_id):
    """Delete all selected witnesses."""
    matter, _ = get_matter_from_url(request, matter_id)
    key = get_session_key("selected_witnesses", matter_id)
    selected = get_selected_ids(request, key)

    if not selected:
        return HttpResponse(status=400, content="No witnesses selected.")

    _selected_witnesses_qs(matter, selected).delete()
    clear_selected_ids(request, key)

    return selection_response("witnessesChanged")


@login_required
@require_POST
def bulk_witnesses_importance(request, matter_id):
    """Bulk set importance on selected witnesses."""
    matter, _ = get_matter_from_url(request, matter_id)
    key = get_session_key("selected_witnesses", matter_id)
    selected = get_selected_ids(request, key)

    if not selected:
        return HttpResponse(status=400, content="No witnesses selected.")

    importance = request.POST.get("importance")
    if importance:
        _selected_witnesses_qs(matter, selected).update(importance=int(importance))

    clear_selected_ids(request, key)
    return selection_response("witnessesChanged")


@login_required
@require_POST
def bulk_witnesses_alignment(request, matter_id):
    """Bulk set alignment on selected witnesses."""
    matter, _ = get_matter_from_url(request, matter_id)
    key = get_session_key("selected_witnesses", matter_id)
    selected = get_selected_ids(request, key)

    if not selected:
        return HttpResponse(status=400, content="No witnesses selected.")

    alignment = request.POST.get("alignment")
    valid_alignments = {value for value, _ in Witness.ALIGNMENT_CHOICES}
    if alignment not in valid_alignments:
        return HttpResponse(status=400, content="Invalid alignment.")

    _selected_witnesses_qs(matter, selected).update(alignment=alignment)

    clear_selected_ids(request, key)
    return selection_response("witnessesChanged")


@login_required
def bulk_witnesses_affiliation(request, matter_id):
    """Bulk set affiliation: GET shows the modal, POST applies.

    Affiliation is the witness's faction, so the modal offers the
    matter's existing affiliations for reuse; an empty value clears."""
    matter, _ = get_matter_from_url(request, matter_id)
    key = get_session_key("selected_witnesses", matter_id)
    selected = get_selected_ids(request, key)

    if not selected:
        return HttpResponse(status=400, content="No witnesses selected.")

    if request.method == "POST":
        affiliation = request.POST.get("affiliation", "").strip()[:255]
        _selected_witnesses_qs(matter, selected).update(affiliation=affiliation)
        clear_selected_ids(request, key)
        return selection_response("witnessesChanged")

    existing_affiliations = (
        Witness.objects.filter(matter=matter)
        .exclude(affiliation="")
        .order_by("affiliation")
        .values_list("affiliation", flat=True)
        .distinct()
    )

    return render(
        request,
        "case/witnesses/bulk_affiliation_modal.html",
        {
            "matter": matter,
            "selected_count": len(selected),
            "existing_affiliations": existing_affiliations,
        },
    )


@login_required
def witness_importance(request, witness_id, importance):
    """Set witness importance."""
    witness = get_object_or_404(Witness, pk=witness_id)
    witness.importance = importance
    witness.save()
    return redirect("case:witnesses-list", matter_id=witness.matter_id)


@login_required
def witness_alignment(request, witness_id, alignment):
    """Set witness alignment."""
    witness = get_object_or_404(Witness, pk=witness_id)
    witness.alignment = alignment
    witness.save()
    return redirect("case:witnesses-list", matter_id=witness.matter_id)


@login_required
def witnesses_filter(request, matter_id):
    """Filter modal for witnesses - GET shows modal, POST saves to session."""
    matter, matters = get_matter_from_url(request, matter_id)
    filter_session_key = get_session_key("witnesses_filter", matter_id)

    if request.method == "POST":
        filter_data = {
            key: value
            for key, value in request.POST.items()
            if key != "csrfmiddlewaretoken"
        }
        request.session[filter_session_key] = filter_data
        request.session.modified = True
        return HttpResponse(status=204, headers={"HX-Trigger": "witnessesChanged"})

    # GET - show filter modal
    filter_data = request.session.get(filter_session_key, {})

    queryset = (
        Witness.objects.filter(matter=matter) if matter else Witness.objects.none()
    )

    filter_obj = WitnessesFilter(filter_data, queryset=queryset)

    return render(
        request, "case/witnesses/filter.html", {"filter": filter_obj, "matter": matter}
    )


@login_required
def witnesses_sort(request, matter_id, order):
    """Sort witnesses by field, toggling asc/desc."""
    filter_session_key = get_session_key("witnesses_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session[filter_session_key] = filter_data
    request.session.modified = True

    return redirect("case:witnesses-list", matter_id=matter_id)


@login_required
def witnesses_filter_importance(request, matter_id, importance_value):
    """Filter witnesses by importance level."""
    filter_session_key = get_session_key("witnesses_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})
    # Set to empty string when 0 (All) is selected, otherwise use the value
    filter_data["importance"] = "" if importance_value == 0 else importance_value

    request.session[filter_session_key] = filter_data

    return redirect("case:witnesses-list", matter_id=matter_id)


def _get_object_for_witnesses(object_type, object_id, view=None):
    """Resolve object + matter + row template for the witness apply flow."""
    if object_type == "highlight":
        obj = get_object_or_404(Highlight, id=object_id)
        matter = obj.document.matter if obj.document else obj.caselaw.matter
        if view == "table":
            row_template = "case/highlights/highlight-row.html"
        elif view == "viewer":
            row_template = "case/highlights/viewer-card.html"
        else:
            row_template = "case/highlights/row.html"
        return obj, matter, row_template, "highlight"
    return None, None, None, None


def _split_witnesses_by_state(obj, matter):
    """Return (linked, available) lists of witnesses for the given object."""
    witnesses = (
        Witness.objects.filter(matter=matter).order_by("name")
        if matter
        else Witness.objects.none()
    )
    linked_ids = set(obj.witnesses.values_list("id", flat=True))
    linked, available = [], []
    for witness in witnesses:
        item = {"id": witness.id, "name": witness.name}
        if witness.id in linked_ids:
            linked.append(item)
        else:
            available.append(item)
    return linked, available, witnesses.exists()


@login_required
def witnesses_apply_modal(request, object_type, object_id):
    """Open modal to link witnesses to an object."""
    obj, matter, _, _ = _get_object_for_witnesses(object_type, object_id)
    if obj is None:
        return HttpResponse("Invalid object type", status=400)

    view = request.GET.get("view", "")
    linked, available, has_witnesses = _split_witnesses_by_state(obj, matter)
    return render(
        request,
        "case/witnesses/apply-modal.html",
        {
            "object": obj,
            "object_type": object_type,
            "matter": matter,
            "view": view,
            "linked_witnesses": linked,
            "available_witnesses": available,
            "has_witnesses": has_witnesses,
        },
    )


@login_required
def witnesses_search(request, object_type, object_id):
    """Search witnesses for the apply modal."""
    obj, matter, _, _ = _get_object_for_witnesses(object_type, object_id)
    if obj is None:
        return HttpResponse("Invalid object type", status=400)

    query = request.GET.get("q", "").strip()
    view = request.GET.get("view", "")

    witnesses = (
        Witness.objects.filter(matter=matter) if matter else Witness.objects.none()
    )

    if query:
        witnesses = witnesses.filter(name__icontains=query)

    existing_ids = obj.witnesses.values_list("id", flat=True)
    witnesses = witnesses.exclude(id__in=existing_ids).order_by("name")

    return render(
        request,
        "case/witnesses/apply-results.html",
        {
            "witnesses": witnesses,
            "object": obj,
            "object_type": object_type,
            "view": view,
        },
    )


def _row_context_for_object(object_type, obj, matter, request):
    """Context for re-rendering a row after a witness change."""
    context = {
        object_type: obj,
        "importance_choices": range(7, 0, -1),
        "matter": matter,
    }
    if object_type == "highlight" and matter:
        selected_session_key = get_session_key("selected_highlights", matter.id)
        context["selected_highlights"] = request.session.get(selected_session_key, [])
    return context


@login_required
@require_POST
def add_witness_to(request, object_type, object_id):
    """Add a witness to an object."""
    view = request.POST.get("view")
    obj, matter, row_template, context_key = _get_object_for_witnesses(
        object_type, object_id, view
    )
    if obj is None:
        return HttpResponse("Invalid object type", status=400)

    witness_id = request.POST.get("witness_id")
    if witness_id:
        try:
            witness = Witness.objects.get(id=witness_id, matter=matter)
            obj.witnesses.add(witness)
        except Witness.DoesNotExist:
            pass

    return render(
        request,
        row_template,
        _row_context_for_object(context_key, obj, matter, request),
    )


@login_required
@require_POST
def remove_witness_from(request, object_type, object_id):
    """Remove a witness from an object."""
    view = request.POST.get("view")
    obj, matter, row_template, context_key = _get_object_for_witnesses(
        object_type, object_id, view
    )
    if obj is None:
        return HttpResponse("Invalid object type", status=400)

    witness_id = request.POST.get("witness_id")
    if witness_id:
        try:
            witness = Witness.objects.get(id=witness_id)
            obj.witnesses.remove(witness)
        except Witness.DoesNotExist:
            pass

    return render(
        request,
        row_template,
        _row_context_for_object(context_key, obj, matter, request),
    )


@login_required
@require_POST
def witnesses_apply_modal_action(request, object_type, object_id):
    """Add or remove a witness and re-render the modal + OOB row update."""
    view = request.POST.get("view", "")
    obj, matter, row_template, context_key = _get_object_for_witnesses(
        object_type, object_id, view
    )
    if obj is None:
        return HttpResponse("Invalid object type", status=400)

    witness = get_object_or_404(
        Witness, id=request.POST.get("witness_id"), matter=matter
    )
    action = request.POST.get("action")

    if action == "add":
        obj.witnesses.add(witness)
    elif action == "remove":
        obj.witnesses.remove(witness)
    else:
        return HttpResponse("Invalid action", status=400)

    linked, available, has_witnesses = _split_witnesses_by_state(obj, matter)
    modal_html = render_to_string(
        "case/witnesses/apply-modal.html",
        {
            "object": obj,
            "object_type": object_type,
            "matter": matter,
            "view": view,
            "linked_witnesses": linked,
            "available_witnesses": available,
            "has_witnesses": has_witnesses,
        },
        request=request,
    )

    if view == "table":
        # See note in labels_apply_modal_action: avoid bare <tr> alongside modal.
        response = HttpResponse(modal_html)
        response["HX-Trigger"] = "highlightsChanged"
        return response

    row_context = _row_context_for_object(context_key, obj, matter, request)
    row_context["oob"] = True
    row_html = render_to_string(row_template, row_context, request=request)
    return HttpResponse(modal_html + row_html)
