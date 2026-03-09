from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from apps.case.models import CaseLaw, Document, Fact, Highlight, Label
from apps.case.views import get_matter_from_url, get_session_key, set_last_tab
from apps.matters.models import Matter
from apps.notes.models import Note

from .filters import LabelsFilter
from .forms import LabelsForm
from .get_label_data import get_label_data


@login_required
def labels_index(request, matter_id):
    label_data = get_label_data(request, matter_id)
    set_last_tab(request, matter_id, "labels")

    context = {
        "app": "matters",
        "subapp": "labels",
    } | label_data

    return render(request, "case/labels/main.html", context)


@login_required
def labels_list(request, matter_id):
    label_data = get_label_data(request, matter_id)

    context = {
        "app": "matters",
        "subapp": "labels",
    } | label_data

    return render(request, "case/labels/list.html", context)


@login_required
def add_label(request, matter_id):
    matter, _ = get_matter_from_url(request, matter_id)

    if request.method == "POST":
        form = LabelsForm(request.POST, use_required_attribute=False)
        form.fields["matter"].queryset = Matter.objects.filter(status="Open").order_by(
            "name"
        )

        if form.is_valid():
            form.save()

            return HttpResponse(status=204, headers={"HX-Trigger": "labelsChanged"})

        return render(
            request,
            "case/labels/form.html",
            {"form": form, "edit": False, "matter": matter},
        )
    else:
        form = LabelsForm(initial={"matter": matter}, use_required_attribute=False)
        form.fields["matter"].queryset = Matter.objects.filter(status="Open").order_by(
            "name"
        )

        return render(
            request,
            "case/labels/form.html",
            {"form": form, "edit": False, "matter": matter},
        )


@login_required
def edit_label(request, label_id):
    try:
        label = Label.objects.get(id=label_id)
    except Label.DoesNotExist:
        return HttpResponse(status=404)

    matter_list = Matter.objects.filter(status="Open").order_by("name")

    # Include closed matter if label belongs to one
    if label.matter and label.matter not in matter_list:
        matter_list = matter_list | Matter.objects.filter(pk=label.matter.id)

    if request.method == "POST":
        form = LabelsForm(request.POST, instance=label, use_required_attribute=False)

        form.fields["matter"].queryset = matter_list

        if form.is_valid():
            form.save()

            return HttpResponse(
                status=204,
                headers={"HX-Trigger": "labelsChanged"},
            )

        return render(
            request,
            "case/labels/form.html",
            {"form": form, "label": label, "edit": True, "matter": label.matter},
        )
    else:
        form = LabelsForm(instance=label, use_required_attribute=False)

        form.fields["matter"].queryset = matter_list

        return render(
            request,
            "case/labels/form.html",
            {"form": form, "label": label, "edit": True, "matter": label.matter},
        )


@login_required
def labels_filter(request, matter_id):
    matter, _ = get_matter_from_url(request, matter_id)
    filter_session_key = get_session_key("labels_filter", matter_id)

    if request.method == "POST":
        request.session[filter_session_key] = dict(request.POST)

        return HttpResponse(status=204, headers={"HX-Trigger": "labelsChanged"})
    else:
        filter_data = request.session.get(filter_session_key, {})

        if filter_data:
            filter = LabelsFilter(
                filter_data,
                queryset=Label.objects.all()
                .select_related("matter")
                .order_by("matter__name", "name"),
            )
        else:
            default_filter = {"order_by": "name"}

            filter = LabelsFilter(
                default_filter,
                queryset=Label.objects.all().select_related("matter").order_by("name"),
            )

        return render(
            request, "case/labels/filter.html", {"filter": filter, "matter": matter}
        )


@login_required
def labels_sort(request, matter_id, order):
    filter_session_key = get_session_key("labels_filter", matter_id)
    filter_data = request.session.get(filter_session_key, {})

    current_order = filter_data.get("order_by", "")

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session[filter_session_key] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "labelsChanged"})


@login_required
def delete_label(request, label_id):
    try:
        Label.objects.get(id=label_id).delete()
    except Label.DoesNotExist:
        return HttpResponse(status=404)

    return HttpResponse(status=204, headers={"HX-Trigger": "labelsChanged"})


def _get_object_for_labels(object_type, object_id, view=None):
    """Helper to get object and matter by type for label operations."""
    if object_type == "document":
        obj = get_object_or_404(Document, id=object_id)
        matter = obj.matter
        row_template = "case/documents/row.html"
        context_key = "document"
    elif object_type == "highlight":
        obj = get_object_or_404(Highlight, id=object_id)
        matter = obj.document.matter if obj.document else None
        # Use table row template if view=table, otherwise card template
        if view == "table":
            row_template = "case/highlights/highlight-row.html"
        else:
            row_template = "case/highlights/row.html"
        context_key = "highlight"
    elif object_type == "fact":
        obj = get_object_or_404(Fact, id=object_id)
        matter = obj.matter
        row_template = "case/facts/fact-row.html"
        context_key = "fact"
    elif object_type == "note":
        obj = get_object_or_404(Note, id=object_id)
        matter = obj.matter
        row_template = "case/notes/note-row.html"
        context_key = "note"
    elif object_type == "caselaw":
        obj = get_object_or_404(CaseLaw, id=object_id)
        matter = obj.matter
        row_template = "case/caselaws/row.html"
        context_key = "case_law"
    else:
        return None, None, None, None
    return obj, matter, row_template, context_key


@login_required
def labels_apply_modal(request, object_type, object_id):
    """Open modal to apply labels to an object."""
    obj, matter, _, _ = _get_object_for_labels(object_type, object_id)
    if obj is None:
        return HttpResponse("Invalid object type", status=400)

    view = request.GET.get("view", "")
    return render(
        request,
        "case/labels/apply-modal.html",
        {"object": obj, "object_type": object_type, "matter": matter, "view": view},
    )


@login_required
def labels_search(request, object_type, object_id):
    """Search labels for apply modal."""
    obj, matter, _, _ = _get_object_for_labels(object_type, object_id)
    if obj is None:
        return HttpResponse("Invalid object type", status=400)

    query = request.GET.get("q", "").strip()
    view = request.GET.get("view", "")

    # Get available labels (global + matter-specific)
    if matter:
        labels = Label.objects.filter(Q(matter=None) | Q(matter=matter))
    else:
        labels = Label.objects.filter(matter=None)

    # Filter by search query
    if query:
        labels = labels.filter(name__icontains=query)

    # Exclude already-applied labels
    existing_label_ids = obj.labels.values_list("id", flat=True)
    labels = labels.exclude(id__in=existing_label_ids)

    # Order: global first, then matter-specific, alphabetically
    labels = labels.order_by("matter", "name")

    return render(
        request,
        "case/labels/apply-results.html",
        {"labels": labels, "object": obj, "object_type": object_type, "view": view},
    )


@login_required
def add_label_to(request, object_type, object_id):
    """Add a label to an object."""
    view = request.POST.get("view")
    obj, matter, row_template, context_key = _get_object_for_labels(
        object_type, object_id, view
    )
    if obj is None:
        return HttpResponse("Invalid object type", status=400)

    label_id = request.POST.get("label_id")
    if label_id:
        try:
            label = Label.objects.get(id=label_id)
            obj.labels.add(label)
        except Label.DoesNotExist:
            pass

    context = {context_key: obj, "importance_choices": range(1, 11), "matter": matter}

    # Add selected_caselaws for caselaw row template
    if object_type == "caselaw" and matter:
        selected_session_key = get_session_key("selected_caselaws", matter.id)
        context["selected_caselaws"] = request.session.get(selected_session_key, [])

    return render(request, row_template, context)


@login_required
def remove_label_from(request, object_type, object_id):
    """Remove a label from an object."""
    view = request.POST.get("view")
    obj, matter, row_template, context_key = _get_object_for_labels(
        object_type, object_id, view
    )
    if obj is None:
        return HttpResponse("Invalid object type", status=400)

    label_id = request.POST.get("label_id")
    if label_id:
        try:
            label = Label.objects.get(id=label_id)
            obj.labels.remove(label)
        except Label.DoesNotExist:
            pass

    context = {context_key: obj, "importance_choices": range(1, 11), "matter": matter}

    # Add selected_caselaws for caselaw row template
    if object_type == "caselaw" and matter:
        selected_session_key = get_session_key("selected_caselaws", matter.id)
        context["selected_caselaws"] = request.session.get(selected_session_key, [])

    return render(request, row_template, context)


@login_required
def labels_create_and_apply(request, object_type, object_id):
    """Create a new label and apply it to an object."""
    view = request.POST.get("view")
    obj, matter, row_template, context_key = _get_object_for_labels(
        object_type, object_id, view
    )
    if obj is None:
        return HttpResponse("Invalid object type", status=400)

    name = request.POST.get("name", "").strip()
    color = request.POST.get("color", "gray")

    if name:
        label = Label.objects.create(matter=matter, name=name, color=color)
        obj.labels.add(label)

    context = {context_key: obj, "importance_choices": range(1, 11), "matter": matter}

    # Add selected_caselaws for caselaw row template
    if object_type == "caselaw" and matter:
        selected_session_key = get_session_key("selected_caselaws", matter.id)
        context["selected_caselaws"] = request.session.get(selected_session_key, [])

    return render(request, row_template, context)
