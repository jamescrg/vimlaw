from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from apps.contacts.contacts import get_list_data
from apps.contacts.models import Contact, ContactRelationship
from apps.contacts.relationships.forms import ContactRelationshipForm

TRIGGER = "relationshipChanged"


def get_relationship_rows(contact):
    """Every edge touching the contact, phrased from the contact's side.

    Outbound edges read the type's label, inbound edges its inverse — so
    one stored link renders correctly on both contacts' pages.
    """
    rels = ContactRelationship.objects.filter(
        Q(from_contact=contact) | Q(to_contact=contact)
    ).select_related("from_contact", "to_contact", "relationship_type")
    rows = []
    for rel in rels:
        outbound = rel.from_contact_id == contact.id
        rows.append(
            {
                "rel": rel,
                "label": (
                    rel.relationship_type.label
                    if outbound
                    else rel.relationship_type.display_inverse
                ),
                "other": rel.to_contact if outbound else rel.from_contact,
            }
        )
    rows.sort(key=lambda row: (row["label"].lower(), row["other"].name.lower()))
    return rows


@login_required
def index(request, contact_id):
    """Contact detail - Related tab"""
    request.session["selected_contact_id"] = contact_id
    context = get_list_data(request)
    context["contact_subapp"] = "relationships"
    # NOT "relationships" — get_list_data already uses that key for the
    # contact's matter relationships.
    context["relationship_rows"] = get_relationship_rows(
        get_object_or_404(Contact, pk=contact_id)
    )
    return render(request, "contacts/main.html", context)


@login_required
def table(request, contact_id):
    """The re-renderable table partial (relationshipChanged refresh)."""
    contact = get_object_or_404(Contact, pk=contact_id)
    return render(
        request,
        "contacts/relationships/table.html",
        {
            "selected_contact": contact,
            "relationship_rows": get_relationship_rows(contact),
        },
    )


@login_required
def add(request, contact_id):
    contact = get_object_or_404(Contact, pk=contact_id)
    if request.method == "POST":
        form = ContactRelationshipForm(request.POST, contact=contact)
        if form.is_valid():
            form.save()
            return HttpResponse(status=204, headers={"HX-Trigger": TRIGGER})
    else:
        form = ContactRelationshipForm(contact=contact)
    return render(
        request,
        "contacts/relationships/form.html",
        {"form": form, "selected_contact": contact},
    )


@login_required
def edit(request, contact_id, id):
    contact = get_object_or_404(Contact, pk=contact_id)
    rel = get_object_or_404(
        ContactRelationship.objects.filter(
            Q(from_contact=contact) | Q(to_contact=contact)
        ),
        pk=id,
    )
    if request.method == "POST":
        form = ContactRelationshipForm(request.POST, contact=contact, instance=rel)
        if form.is_valid():
            form.save()
            return HttpResponse(status=204, headers={"HX-Trigger": TRIGGER})
    else:
        form = ContactRelationshipForm(contact=contact, instance=rel)
    return render(
        request,
        "contacts/relationships/form.html",
        {"form": form, "selected_contact": contact, "relationship": rel},
    )


@login_required
@require_POST
def delete(request, contact_id, id):
    contact = get_object_or_404(Contact, pk=contact_id)
    rel = get_object_or_404(
        ContactRelationship.objects.filter(
            Q(from_contact=contact) | Q(to_contact=contact)
        ),
        pk=id,
    )
    rel.delete()
    return HttpResponse(status=204, headers={"HX-Trigger": TRIGGER})
