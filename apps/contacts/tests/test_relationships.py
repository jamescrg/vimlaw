import pytest
from django.db import IntegrityError
from django.urls import reverse

from apps.contacts.models import ContactRelationship, RelationshipType
from apps.contacts.relationships.forms import ContactRelationshipForm

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------


def test_symmetric_type_properties(symmetric_type, asymmetric_type):
    assert symmetric_type.is_symmetric
    assert symmetric_type.display_inverse == "Spouse of"
    assert not asymmetric_type.is_symmetric
    assert asymmetric_type.display_inverse == "Employee of"


def test_self_link_rejected_by_db(contact, symmetric_type):
    with pytest.raises(IntegrityError):
        ContactRelationship.objects.create(
            from_contact=contact,
            to_contact=contact,
            relationship_type=symmetric_type,
        )


def test_exact_duplicate_rejected_by_db(contact, contact_beta, symmetric_type):
    ContactRelationship.objects.create(
        from_contact=contact, to_contact=contact_beta, relationship_type=symmetric_type
    )
    with pytest.raises(IntegrityError):
        ContactRelationship.objects.create(
            from_contact=contact,
            to_contact=contact_beta,
            relationship_type=symmetric_type,
        )


def test_contact_delete_cascades_both_directions(
    contact, contact_beta, symmetric_type, asymmetric_type
):
    ContactRelationship.objects.create(
        from_contact=contact, to_contact=contact_beta, relationship_type=symmetric_type
    )
    ContactRelationship.objects.create(
        from_contact=contact_beta,
        to_contact=contact,
        relationship_type=asymmetric_type,
    )
    contact.delete()
    assert ContactRelationship.objects.count() == 0


def test_type_delete_cascades_links(contact, contact_beta, asymmetric_type):
    ContactRelationship.objects.create(
        from_contact=contact,
        to_contact=contact_beta,
        relationship_type=asymmetric_type,
    )
    asymmetric_type.delete()
    assert ContactRelationship.objects.count() == 0


# --------------------------------------------------------------------------
# Form
# --------------------------------------------------------------------------


def test_choices_both_phrasings_for_asymmetric(symmetric_type, asymmetric_type):
    form = ContactRelationshipForm(contact=None)
    choices = form.fields["type_direction"].choices
    labels = [label for _, label in choices]
    assert labels == sorted(labels, key=str.lower)
    values = {label: value for value, label in choices}
    assert values["Employer of"] == f"{asymmetric_type.id}:f"
    assert values["Employee of"] == f"{asymmetric_type.id}:r"
    assert values["Spouse of"] == f"{symmetric_type.id}:f"


def test_inactive_type_excluded_from_choices(symmetric_type, asymmetric_type):
    asymmetric_type.is_active = False
    asymmetric_type.save()
    form = ContactRelationshipForm(contact=None)
    labels = [label for _, label in form.fields["type_direction"].choices]
    assert "Spouse of" in labels
    assert "Employer of" not in labels
    assert "Employee of" not in labels


def test_forward_save_orientation(contact, contact_beta, asymmetric_type):
    form = ContactRelationshipForm(
        {
            "type_direction": f"{asymmetric_type.id}:f",
            "other_contact": contact_beta.id,
            "notes": "Runs the ashram",
        },
        contact=contact,
    )
    assert form.is_valid(), form.errors
    rel = form.save()
    assert rel.from_contact == contact
    assert rel.to_contact == contact_beta
    assert rel.notes == "Runs the ashram"


def test_reverse_save_orientation(contact, contact_beta, asymmetric_type):
    form = ContactRelationshipForm(
        {
            "type_direction": f"{asymmetric_type.id}:r",
            "other_contact": contact_beta.id,
            "notes": "",
        },
        contact=contact,
    )
    assert form.is_valid(), form.errors
    rel = form.save()
    assert rel.from_contact == contact_beta
    assert rel.to_contact == contact
    assert rel.notes is None


def test_self_link_rejected_by_form(contact, symmetric_type):
    form = ContactRelationshipForm(
        {
            "type_direction": f"{symmetric_type.id}:f",
            "other_contact": contact.id,
            "notes": "",
        },
        contact=contact,
    )
    assert not form.is_valid()
    assert "other_contact" in form.errors


@pytest.mark.parametrize("orientation", ["f", "r"])
def test_duplicate_rejected_either_orientation(
    contact, contact_beta, asymmetric_type, orientation
):
    ContactRelationship.objects.create(
        from_contact=contact,
        to_contact=contact_beta,
        relationship_type=asymmetric_type,
    )
    form = ContactRelationshipForm(
        {
            "type_direction": f"{asymmetric_type.id}:{orientation}",
            "other_contact": contact_beta.id,
            "notes": "",
        },
        contact=contact,
    )
    assert not form.is_valid()
    assert "already have this relationship" in str(form.non_field_errors())


def test_edit_initial_from_each_side(contact, contact_beta, asymmetric_type):
    rel = ContactRelationship.objects.create(
        from_contact=contact,
        to_contact=contact_beta,
        relationship_type=asymmetric_type,
    )
    from_side = ContactRelationshipForm(contact=contact, instance=rel)
    assert from_side.initial["type_direction"] == f"{asymmetric_type.id}:f"
    assert from_side.initial["other_contact"] == contact_beta

    to_side = ContactRelationshipForm(contact=contact_beta, instance=rel)
    assert to_side.initial["type_direction"] == f"{asymmetric_type.id}:r"
    assert to_side.initial["other_contact"] == contact


def test_edit_can_resave_same_pair(contact, contact_beta, asymmetric_type):
    rel = ContactRelationship.objects.create(
        from_contact=contact,
        to_contact=contact_beta,
        relationship_type=asymmetric_type,
    )
    form = ContactRelationshipForm(
        {
            "type_direction": f"{asymmetric_type.id}:r",
            "other_contact": contact_beta.id,
            "notes": "Flipped",
        },
        contact=contact,
        instance=rel,
    )
    assert form.is_valid(), form.errors
    rel = form.save()
    assert rel.from_contact == contact_beta
    assert rel.to_contact == contact
    assert ContactRelationship.objects.count() == 1


# --------------------------------------------------------------------------
# Contact tab views
# --------------------------------------------------------------------------


def test_related_tab_shows_each_side_of_one_edge(
    client, contact, contact_beta, asymmetric_type
):
    ContactRelationship.objects.create(
        from_contact=contact,
        to_contact=contact_beta,
        relationship_type=asymmetric_type,
    )
    response = client.get(reverse("contacts:detail-related", args=[contact.id]))
    assert response.status_code == 200
    assert "Employer of" in response.content.decode()

    response = client.get(reverse("contacts:detail-related", args=[contact_beta.id]))
    assert response.status_code == 200
    assert "Employee of" in response.content.decode()


def test_table_partial_renders(client, contact, contact_beta, symmetric_type):
    ContactRelationship.objects.create(
        from_contact=contact_beta,
        to_contact=contact,
        relationship_type=symmetric_type,
    )
    response = client.get(reverse("contacts:relationship-table", args=[contact.id]))
    assert response.status_code == 200
    content = response.content.decode()
    assert "Spouse of" in content
    assert contact_beta.name in content


def test_add_relationship(client, contact, contact_beta, symmetric_type):
    url = reverse("contacts:add-relationship", args=[contact.id])
    response = client.get(url)
    assert response.status_code == 200

    response = client.post(
        url,
        {
            "type_direction": f"{symmetric_type.id}:f",
            "other_contact": contact_beta.id,
            "notes": "",
        },
    )
    assert response.status_code == 204
    assert response.headers["HX-Trigger"] == "relationshipChanged"
    assert ContactRelationship.objects.count() == 1


def test_add_invalid_rerenders_form(client, contact, symmetric_type):
    response = client.post(
        reverse("contacts:add-relationship", args=[contact.id]),
        {
            "type_direction": f"{symmetric_type.id}:f",
            "other_contact": contact.id,
            "notes": "",
        },
    )
    assert response.status_code == 200
    assert ContactRelationship.objects.count() == 0


def test_edit_relationship(client, contact, contact_beta, asymmetric_type):
    rel = ContactRelationship.objects.create(
        from_contact=contact,
        to_contact=contact_beta,
        relationship_type=asymmetric_type,
    )
    url = reverse("contacts:edit-relationship", args=[contact_beta.id, rel.id])
    response = client.get(url)
    assert response.status_code == 200

    response = client.post(
        url,
        {
            "type_direction": f"{asymmetric_type.id}:r",
            "other_contact": contact.id,
            "notes": "Updated",
        },
    )
    assert response.status_code == 204
    assert response.headers["HX-Trigger"] == "relationshipChanged"
    rel.refresh_from_db()
    assert rel.notes == "Updated"


def test_edit_scoped_to_contact(
    client, contact, contact_beta, contact_gamma, symmetric_type
):
    rel = ContactRelationship.objects.create(
        from_contact=contact,
        to_contact=contact_beta,
        relationship_type=symmetric_type,
    )
    response = client.get(
        reverse("contacts:edit-relationship", args=[contact_gamma.id, rel.id])
    )
    assert response.status_code == 404


def test_delete_relationship(client, contact, contact_beta, symmetric_type):
    rel = ContactRelationship.objects.create(
        from_contact=contact,
        to_contact=contact_beta,
        relationship_type=symmetric_type,
    )
    response = client.post(
        reverse("contacts:delete-relationship", args=[contact.id, rel.id])
    )
    assert response.status_code == 204
    assert response.headers["HX-Trigger"] == "relationshipChanged"
    assert ContactRelationship.objects.count() == 0


# --------------------------------------------------------------------------
# Settings: relationship-type CRUD
# --------------------------------------------------------------------------


def test_settings_index_lists_types(client, symmetric_type):
    response = client.get(reverse("settings:contacts-index"))
    assert response.status_code == 200
    assert "Spouse of" in response.content.decode()


def test_add_relationship_type(client):
    url = reverse("settings:add-relationship-type")
    response = client.get(url)
    assert response.status_code == 200

    response = client.post(
        url, {"label": "Guardian of", "inverse_label": "Ward of", "is_active": "True"}
    )
    assert response.status_code == 204
    assert response.headers["HX-Trigger"] == "relationshipTypeListReload"
    assert RelationshipType.objects.filter(label="Guardian of").exists()


def test_edit_relationship_type(client, asymmetric_type):
    response = client.post(
        reverse("settings:edit-relationship-type", args=[asymmetric_type.id]),
        {"label": "Boss of", "inverse_label": "Reports to", "is_active": "True"},
    )
    assert response.status_code == 204
    asymmetric_type.refresh_from_db()
    assert asymmetric_type.label == "Boss of"


def test_delete_relationship_type_cascades(
    client, contact, contact_beta, symmetric_type
):
    ContactRelationship.objects.create(
        from_contact=contact,
        to_contact=contact_beta,
        relationship_type=symmetric_type,
    )
    response = client.post(
        reverse("settings:delete-relationship-type", args=[symmetric_type.id])
    )
    assert response.status_code == 204
    assert response.headers["HX-Trigger"] == "relationshipTypeListReload"
    assert not RelationshipType.objects.filter(id=symmetric_type.id).exists()
    assert not ContactRelationship.objects.exists()


def test_relationship_type_filter(client, symmetric_type, asymmetric_type):
    asymmetric_type.is_active = False
    asymmetric_type.save()

    response = client.post(
        reverse("settings:relationship-type-filter", args=["inactive"])
    )
    assert response.status_code == 204
    assert response.headers["HX-Trigger"] == "relationshipTypeListReload"
    response = client.get(reverse("settings:relationship-type-list"))
    content = response.content.decode()
    assert "Employer of" in content
    assert "Spouse of" not in content
