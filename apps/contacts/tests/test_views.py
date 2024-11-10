import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

from apps.contacts.models import Contact
from apps.matters.models import Relationship

pytestmark = pytest.mark.django_db


def test_index(client, folder, contact):
    response = client.get("/contacts/")
    assert response.status_code == 200

    response = client.get(reverse("contacts:contacts"))
    assert response.status_code == 200

    # no selected folder
    response = client.get(reverse("contacts:contacts"))
    assertTemplateUsed(response, "contacts/content.html")
    assert not response.context["contacts"]

    # folder selected
    response = client.get(reverse("contacts:select", args=[contact.id]))
    assert response.status_code == 204

    response = client.get(reverse("contacts:contacts"))
    assert response.context["selected_folder"] == folder


def test_select(client, folder, contact):
    response = client.get(f"/contacts/{contact.id}")
    assert response.status_code == 204


def test_add_get(client, folder, contact):
    # test without a selected folder
    response = client.get("/contacts/add")
    assert response.status_code == 200
    assertTemplateUsed(response, "contacts/form.html")

    response = client.get(reverse("contacts:select", args=[contact.id]))
    assert response.status_code == 204

    # set a selected folder
    response = client.get("/contacts/add")
    assert response.context["selected_folder"] == folder
    assert response.status_code == 200


def test_add_post(client, folder, contact_data):
    response = client.post("/contacts/add", contact_data)
    assert response.status_code == 302
    found = Contact.objects.filter(name=contact_data["name"]).first()
    assert found


def test_edit_get(client, contact):
    response = client.get(f"/contacts/{contact.id}/edit")
    assert response.status_code == 200
    assertTemplateUsed(response, "contacts/form.html")


def test_edit_post(client, folder, contact):
    data = {
        "folder": folder.id,
        "name": "Descartes",
        "phone1": "440.500.6000",
        "client_status": "Current",
    }

    response = client.post(f"/contacts/{contact.id}/edit", data)
    assert response.status_code == 302

    found = Contact.objects.filter(name="Descartes").exists()
    assert found


def test_delete(client, contact):
    response = client.get(f"/contacts/{contact.id}/delete")
    assert response.status_code == 302
    found = Contact.objects.filter(pk=contact.id).exists()
    assert not found


def test_assign_get(client, contact):
    response = client.get(f"/contacts/{contact.id}/assign")
    assert response.status_code == 200
    assertTemplateUsed(response, "contacts/assign.html")


def test_assign_post(client, contact, matter, role):
    data = {"matter_id": matter.id, "role_id": role.id}
    response = client.post(f"/contacts/{contact.id}/assign/store", data)
    assert response.status_code == 204


def test_remove_get(client, contact):
    response = client.get(f"/contacts/{contact.id}/remove")
    assert response.status_code == 200
    assertTemplateUsed(response, "contacts/remove.html")


def test_remove_post(client, contact, matter, role):
    data = {"matter_id": matter.id, "role_id": role.id}
    client.post(f"/contacts/{contact.id}/assign/store", data)

    rel = Relationship.objects.filter(contact=contact, matter=matter).latest("id")
    data = {"relationship_id": rel.id}
    response = client.post(f"/contacts/{contact.id}/remove/store", data)

    assert response.status_code == 404


def test_add_intake(client, intake, contact, folder):
    folder.id = 313
    folder.save()
    contact.folder = folder
    contact.save()
    response = client.get(f"/contacts/{intake.id}/add_intake")
    assert response.status_code == 200
