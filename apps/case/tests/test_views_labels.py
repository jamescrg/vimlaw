import pytest
from pytest_django.asserts import assertTemplateUsed

from apps.case.models import Label

pytestmark = pytest.mark.django_db


class TestLabelsIndex:
    def test_index_requires_login(self, client, matter):
        client.logout()
        response = client.get(f"/case/{matter.id}/labels/")
        assert response.status_code == 302
        assert "/accounts/login/" in response.url

    def test_index_authenticated(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/labels/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/labels/main.html")


class TestLabelsList:
    def test_list_authenticated(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/labels/list/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/labels/list.html")

    def test_list_shows_labels(self, client_with_matter, label):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/labels/list/")
        assert response.status_code == 200
        assert b"Important" in response.content


class TestAddLabel:
    def test_add_get(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/labels/add/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/labels/form.html")

    def test_add_post(self, client_with_matter, matter):
        matter_id = client_with_matter.matter.id
        data = {
            "name": "New Label",
            "color": "green",
            "matter": matter.id,
        }
        response = client_with_matter.post(f"/case/{matter_id}/labels/add/", data)
        assert response.status_code == 204
        assert Label.objects.filter(name="New Label").exists()

    def test_add_global_label(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        data = {
            "name": "Global New",
            "color": "purple",
            "matter": "",  # Empty for global
        }
        response = client_with_matter.post(f"/case/{matter_id}/labels/add/", data)
        assert response.status_code == 204
        label = Label.objects.get(name="Global New")
        assert label.is_global


class TestEditLabel:
    def test_edit_get(self, client_with_matter, label):
        response = client_with_matter.get(f"/case/labels/{label.id}/edit/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/labels/form.html")

    def test_edit_post(self, client_with_matter, label, matter):
        data = {
            "name": "Updated Label",
            "color": "blue",
            "matter": matter.id,
        }
        response = client_with_matter.post(f"/case/labels/{label.id}/edit/", data)
        assert response.status_code == 204
        label.refresh_from_db()
        assert label.name == "Updated Label"
        assert label.color == "blue"

    def test_edit_nonexistent(self, client_with_matter):
        response = client_with_matter.get("/case/labels/99999/edit/")
        assert response.status_code == 404


class TestDeleteLabel:
    def test_delete(self, client_with_matter, label):
        label_id = label.id
        response = client_with_matter.post(f"/case/labels/{label_id}/delete/")
        assert response.status_code == 204
        assert not Label.objects.filter(id=label_id).exists()

    def test_delete_nonexistent(self, client_with_matter):
        response = client_with_matter.post("/case/labels/99999/delete/")
        assert response.status_code == 404


class TestLabelsFilter:
    def test_filter_get(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/labels/filter/")
        assert response.status_code == 200

    def test_filter_post(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        data = {"order_by": "name"}
        response = client_with_matter.post(f"/case/{matter_id}/labels/filter/", data)
        assert response.status_code == 204


class TestLabelsSort:
    def test_sort_by_name(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        response = client_with_matter.get(f"/case/{matter_id}/labels/sort/name/")
        assert response.status_code == 204

    def test_sort_toggles_direction(self, client_with_matter):
        matter_id = client_with_matter.matter.id
        filter_key = f"labels_filter_{matter_id}"

        # First sort
        client_with_matter.get(f"/case/{matter_id}/labels/sort/name/")
        session = client_with_matter.session
        filter_data = session.get(filter_key, {})
        assert filter_data.get("order_by") == "name"

        # Second sort - toggle
        client_with_matter.get(f"/case/{matter_id}/labels/sort/name/")
        session = client_with_matter.session
        filter_data = session.get(filter_key, {})
        assert filter_data.get("order_by") == "-name"


class TestLabelsApply:
    def test_apply_modal_document(self, client_with_matter, document):
        response = client_with_matter.get(f"/case/labels/apply/document/{document.id}/")
        assert response.status_code == 200
        assertTemplateUsed(response, "case/labels/apply-modal.html")

    def test_apply_modal_highlight(self, client_with_matter, highlight):
        response = client_with_matter.get(
            f"/case/labels/apply/highlight/{highlight.id}/"
        )
        assert response.status_code == 200

    def test_apply_modal_fact(self, client_with_matter, fact):
        response = client_with_matter.get(f"/case/labels/apply/fact/{fact.id}/")
        assert response.status_code == 200

    def test_apply_modal_invalid_type(self, client_with_matter):
        response = client_with_matter.get("/case/labels/apply/invalid/1/")
        assert response.status_code == 400


class TestLabelsSearch:
    def test_search_for_document(self, client_with_matter, document, label):
        response = client_with_matter.get(
            f"/case/labels/search/document/{document.id}/?q=Important"
        )
        assert response.status_code == 200

    def test_search_empty_query(self, client_with_matter, document):
        response = client_with_matter.get(
            f"/case/labels/search/document/{document.id}/"
        )
        assert response.status_code == 200


class TestAddLabelTo:
    def test_add_label_to_document(self, client_with_matter, document, label):
        response = client_with_matter.post(
            f"/case/labels/add-to/document/{document.id}/",
            {"label_id": label.id},
        )
        assert response.status_code == 200
        assert label in document.labels.all()

    def test_add_label_to_highlight(self, client_with_matter, highlight, label):
        response = client_with_matter.post(
            f"/case/labels/add-to/highlight/{highlight.id}/",
            {"label_id": label.id},
        )
        assert response.status_code == 200
        assert label in highlight.labels.all()

    def test_add_label_to_fact(self, client_with_matter, fact, label):
        response = client_with_matter.post(
            f"/case/labels/add-to/fact/{fact.id}/",
            {"label_id": label.id},
        )
        assert response.status_code == 200
        assert label in fact.labels.all()


class TestRemoveLabelFrom:
    def test_remove_label_from_document(self, client_with_matter, document, label):
        document.labels.add(label)
        response = client_with_matter.post(
            f"/case/labels/remove-from/document/{document.id}/",
            {"label_id": label.id},
        )
        assert response.status_code == 200
        assert label not in document.labels.all()

    def test_remove_label_from_highlight(self, client_with_matter, highlight, label):
        highlight.labels.add(label)
        response = client_with_matter.post(
            f"/case/labels/remove-from/highlight/{highlight.id}/",
            {"label_id": label.id},
        )
        assert response.status_code == 200
        assert label not in highlight.labels.all()

    def test_remove_label_from_fact(self, client_with_matter, fact, label):
        fact.labels.add(label)
        response = client_with_matter.post(
            f"/case/labels/remove-from/fact/{fact.id}/",
            {"label_id": label.id},
        )
        assert response.status_code == 200
        assert label not in fact.labels.all()


class TestCreateAndApplyLabel:
    def test_create_and_apply_to_document(self, client_with_matter, document):
        response = client_with_matter.post(
            f"/case/labels/create-and-apply/document/{document.id}/",
            {"name": "Brand New Label", "color": "orange"},
        )
        assert response.status_code == 200
        new_label = Label.objects.get(name="Brand New Label")
        assert new_label in document.labels.all()

    def test_create_and_apply_to_highlight(self, client_with_matter, highlight):
        response = client_with_matter.post(
            f"/case/labels/create-and-apply/highlight/{highlight.id}/",
            {"name": "Highlight Label", "color": "yellow"},
        )
        assert response.status_code == 200
        new_label = Label.objects.get(name="Highlight Label")
        assert new_label in highlight.labels.all()
