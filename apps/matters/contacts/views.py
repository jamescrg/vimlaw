from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.contacts.functions.load_contacts import load_contacts
from apps.contacts.models import Contact
from apps.matters.contacts.filters import MatterContactFilter
from apps.matters.models import Group, Matter, Relationship, Role

DEFAULT_MATTER_CONTACT_FILTER = {"order_by": "group"}


def get_contact_list(request, matter):
    """Build the contact list with filtering and sorting applied."""
    session_key = f"matter_contacts_filter_{matter.id}"
    filter_data = request.session.get(session_key, {})

    contacts_qs = load_contacts(matter)

    if filter_data:
        contacts_qs = MatterContactFilter(filter_data, queryset=contacts_qs).qs
    else:
        contacts_qs = MatterContactFilter(
            DEFAULT_MATTER_CONTACT_FILTER, queryset=contacts_qs
        ).qs

    # Build unified list with matter.client as first row if exists
    contact_list = []

    if matter.client:
        # Only include client row if not filtering by non-Client group
        group_filter = filter_data.get("group", "")
        if isinstance(group_filter, list):
            group_filter = group_filter[0] if group_filter else ""
        # Check if filtering by Client group (ID) or no filter
        client_group = Group.objects.filter(name="Client").first()
        if not group_filter or str(group_filter) == str(
            client_group.id if client_group else ""
        ):
            contact_list.append(
                {
                    "group": "Client",
                    "role_name": "Client",
                    "contact": matter.client,
                    "relationship_id": None,
                    "is_client": True,
                }
            )

    for rel in contacts_qs:
        contact_list.append(
            {
                "group": rel.group.name,
                "role_name": rel.role.name,
                "contact": rel.contact,
                "relationship_id": rel.id,
                "is_client": False,
            }
        )

    current_order = filter_data.get("order_by", "group") if filter_data else "group"
    if isinstance(current_order, list):
        current_order = current_order[0] if current_order else "group"

    # Add band index for visual grouping when sorted by group
    order_field = current_order.lstrip("-")
    if order_field == "group":
        current_group = None
        band = 0
        for item in contact_list:
            if item["group"] != current_group:
                current_group = item["group"]
                band = 1 - band
            item["band"] = band

    return {
        "contacts": contact_list,
        "current_order": order_field,
        "session_key": session_key,
    }


@login_required
def index(request, id):
    matter = get_object_or_404(Matter, pk=id)

    contact_data = get_contact_list(request, matter)

    context = {
        "app": "matters",
        "subapp": "contacts",
        "matter": matter,
        **contact_data,
    }

    return render(request, "matters/contacts/list.html", context)


@login_required
def contact_list(request, id):
    """HTMX endpoint to reload the contact table."""
    matter = get_object_or_404(Matter, pk=id)

    contact_data = get_contact_list(request, matter)

    context = {
        "matter": matter,
        **contact_data,
    }

    return render(request, "matters/contacts/contact-table.html", context)


@login_required
def contact_filter(request, id):
    """Handle filter form display and submission."""
    matter = get_object_or_404(Matter, pk=id)
    session_key = f"matter_contacts_filter_{matter.id}"

    if request.method == "POST":
        request.session[session_key] = request.POST
        return HttpResponse(status=204, headers={"HX-Trigger": "contactsReload"})

    filter_data = request.session.get(session_key, {})
    contacts_qs = load_contacts(matter)
    filter_form = MatterContactFilter(filter_data, queryset=contacts_qs)

    context = {
        "filter": filter_form,
        "matter": matter,
        "session_key": session_key,
    }

    return render(request, "matters/contacts/filter.html", context)


@login_required
def contact_sort(request, id, order):
    """Handle column sorting."""
    matter = get_object_or_404(Matter, pk=id)
    session_key = f"matter_contacts_filter_{matter.id}"
    filter_data = dict(request.session.get(session_key, {}))

    current_order = filter_data.get("order_by", "")
    if isinstance(current_order, list):
        current_order = current_order[0] if current_order else ""

    if current_order == order:
        new_order = f"-{order}" if not current_order.startswith("-") else order
    else:
        new_order = order

    filter_data["order_by"] = new_order
    request.session[session_key] = filter_data

    return HttpResponse(status=204, headers={"HX-Trigger": "contactsReload"})


@login_required
def assign(request, id):
    matter = get_object_or_404(Matter, pk=id)

    context = {
        "app": "matters",
        "subapp": "contacts",
        "matter": matter,
    }

    return render(request, "matters/contacts/assign.html", context)


@login_required
def assign_results(request, id):
    matter = get_object_or_404(Matter, pk=id)
    text = request.POST.get("search_text")

    if text:
        contacts = Contact.objects.filter(name__icontains=text).order_by("name")
    else:
        contacts = None

    context = {
        "matter": matter,
        "contacts": contacts,
    }

    return render(request, "matters/contacts/results.html", context)


@login_required
def assign_role(request, matter_id, contact_id):
    matter = get_object_or_404(Matter, pk=matter_id)
    contact = get_object_or_404(Contact, pk=contact_id)
    groups = Group.objects.filter(is_active=True)
    roles = (
        Role.objects.filter(is_active=True)
        .exclude(name__in=["Client", "Client (Invoicing)"])
        .order_by("name")
    )

    context = {
        "app": "matters",
        "subapp": "contacts",
        "matter": matter,
        "contact": contact,
        "groups": groups,
        "roles": roles,
        "edit": False,
        "action": "/matters/assign/store",
    }

    return render(request, "matters/contacts/assign-role.html", context)


@login_required
def assign_store(request):
    matter = get_object_or_404(Matter, pk=request.POST["matter_id"])
    contact = get_object_or_404(Contact, pk=request.POST["contact_id"])
    group = get_object_or_404(Group, pk=request.POST["group_id"])
    role = get_object_or_404(Role, pk=request.POST["role_id"])

    Relationship.objects.create(matter=matter, contact=contact, group=group, role=role)

    return redirect(f"/matters/{matter.id}/contacts")


@login_required
def assign_edit(request, id):
    relationship = get_object_or_404(Relationship, pk=id)

    matter = get_object_or_404(Matter, pk=relationship.matter_id)
    contact = get_object_or_404(Contact, pk=relationship.contact_id)
    groups = Group.objects.filter(is_active=True)
    roles = (
        Role.objects.filter(is_active=True)
        .exclude(name__in=["Client", "Client (Invoicing)"])
        .order_by("name")
    )

    context = {
        "app": "matters",
        "subapp": "contacts",
        "matter": matter,
        "contact": contact,
        "relationship": relationship,
        "groups": groups,
        "roles": roles,
        "edit": True,
        "action": f"/matters/assign/{relationship.id}/update",
    }

    return render(request, "matters/contacts/assign-role.html", context)


@login_required
def assign_update(request, id):
    relationship = get_object_or_404(Relationship, pk=id)
    relationship.group_id = request.POST.get("group_id")
    relationship.role_id = request.POST.get("role_id")
    relationship.save()
    matter = get_object_or_404(Matter, pk=relationship.matter_id)
    return redirect(f"/matters/{matter.id}/contacts")


@login_required
def assign_delete(request, id):
    relationship = get_object_or_404(Relationship, pk=id)
    matter = get_object_or_404(Matter, pk=relationship.matter_id)
    relationship.delete()
    return redirect(f"/matters/{matter.id}/contacts")
