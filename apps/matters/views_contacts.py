from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.shortcuts import render
from django.shortcuts import get_object_or_404

from apps.contacts.models import Contact
from apps.matters.models import Matter
from apps.matters.models import Proceeding
from apps.matters.models import Relationship
from apps.matters.models import Role
from apps.matters.load_contacts import load_contacts


@login_required
def index(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    relationship_groups = load_contacts(matter)

    context = {
        "page": "matters",
        "submodule": "contacts",
        "matter": matter,
        "proceeding": proceeding,
        "relationship_groups": relationship_groups,
    }

    return render(request, "matters/contacts/list.html", context)


@login_required
def assign(request, id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()

    context = {
        "page": "matters",
        "submodule": "contacts",
        "matter": matter,
        "proceeding": proceeding,
    }

    return render(request, "matters/contacts/assign.html", context)


@login_required
def assign_results(request, id):
    matter = get_object_or_404(Matter, pk=id)
    text = request.POST.get("search_text")

    if text:
        contacts = Contact.objects.filter(name__contains=text).order_by("name")
    else:
        contacts = None

    context = {
        "matter": matter,
        "contacts": contacts,
    }

    return render(request, "matters/contacts/results.html", context)


@login_required
def assign_role(request, id, contact_id):
    matter = get_object_or_404(Matter, pk=id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()
    contact = get_object_or_404(Contact, pk=contact_id)
    roles = Role.objects.all().order_by("name")

    context = {
        "page": "matters",
        "submodule": "contacts",
        "matter": matter,
        "proceeding": proceeding,
        "contact": contact,
        "roles": roles,
        "edit": False,
        "action": "/matters/assign/store",
    }

    return render(request, "matters/contacts/assign-role.html", context)


@login_required
def assign_store(request):
    matter = get_object_or_404(Matter, pk=request.POST["matter_id"])
    contact = get_object_or_404(Contact, pk=request.POST["contact_id"])
    role = get_object_or_404(Role, pk=request.POST["role_id"])

    relationship = Relationship.objects.create(
        matter=matter, contact=contact, role=role
    )
    relationship.save()

    return redirect(f"/matters/{matter.id}/contacts")


@login_required
def assign_edit(request, id):
    relationship = get_object_or_404(Relationship, pk=id)

    matter = get_object_or_404(Matter, pk=relationship.matter_id)
    proceeding = Proceeding.objects.filter(matter=matter.id).order_by("-id").first()
    contact = get_object_or_404(Contact, pk=relationship.contact_id)
    roles = Role.objects.all().order_by("name")

    context = {
        "page": "matters",
        "submodule": "contacts",
        "matter": matter,
        "proceeding": proceeding,
        "contact": contact,
        "relationship": relationship,
        "roles": roles,
        "edit": True,
        "action": f"/matters/assign/{relationship.id}/update",
    }

    return render(request, "matters/contacts/assign-role.html", context)


@login_required
def assign_update(request, id):
    relationship = get_object_or_404(Relationship, pk=id)
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
