import pytest

from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.contacts.models import Contact
from apps.folders.models import Folder
from apps.matters.models import Relationship


pytestmark = pytest.mark.django_db


def test_assign(client, matter):
    response = client.get(f"/matters/{matter.id}/contacts/assign")
    assert response.status_code == 200
    assertTemplateUsed(response, "matters/contacts/assign.html")


def test_assign_results(client, matter, contact):
    data = {"search_text": "Gandhi"}
    response = client.post(f"/matters/{matter.id}/contacts/assign/results", data)
    assert response.status_code == 200
    assertTemplateUsed(response, "matters/contacts/results.html")
    assert response.context["contacts"]


def test_assign_role(client, matter, contact):
    response = client.get(f"/matters/{matter.id}/assign/{contact.id}")
    assert response.status_code == 200
    assertTemplateUsed(response, "matters/contacts/assign-role.html")


def test_assign_store(client, matter, contact, role):
    data = {
        "matter_id": matter.id,
        "contact_id": contact.id,
        "role_id": role.id,
    }
    response = client.post("/matters/assign/store", data)
    assert response.status_code == 302
    found = Relationship.objects.filter(matter=matter).first()
    assert found


def test_assign_edit(client, relationship):
    response = client.get(f"/matters/assign/{relationship.id}/edit")
    assert response.status_code == 200
    assertTemplateUsed(response, "matters/contacts/assign-role.html")


def test_assign_update(client, relationship, role):
    data = {"role_id": role.id}
    response = client.post(f"/matters/assign/{relationship.id}/update", data)
    assert response.status_code == 302
    found = Relationship.objects.filter(role_id=role.id).first()
    assert found


def test_delete(client, relationship):
    response = client.get(f"/matters/assign/{relationship.id}/delete")
    assert response.status_code == 302
    found = Relationship.objects.filter(pk=relationship.id).exists()
    assert not found
