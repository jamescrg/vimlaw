from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.case.models import Witness
from apps.case.views import get_matter_from_url, get_session_key, set_last_tab

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

    return {
        "witnesses": witnesses,
        "current_order": current_order,
        "keyword": keyword,
        "importances": list(range(1, 11)),
        "importance_value": importance_value,
        "selected_importance": (
            f"Importance {importance_value}" if importance_value else ""
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
    witness.delete()

    return HttpResponse(status=204, headers={"HX-Trigger": "witnessesChanged"})


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
